//! Optional TLS support for PostgreSQL connections.
//!
//! Provides a [`PgTlsConnector`] enum that dispatches between plain (no TLS) and
//! rustls-backed connections based on the `sslmode` parameter in the connection string.

use std::error::Error as StdError;
use std::future::Future;
use std::io;
use std::pin::Pin;
use std::task::{Context, Poll};

use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio_postgres::tls::{
    ChannelBinding, MakeTlsConnect, NoTls, NoTlsStream, TlsConnect, TlsStream,
};
use tokio_postgres::Socket;
use tokio_postgres_rustls::MakeRustlsConnect;
use tracing::info;

// Associated types from MakeRustlsConnect -- lets us reference them without
// naming the crate-private concrete types.
type RustlsTc = <MakeRustlsConnect as MakeTlsConnect<Socket>>::TlsConnect;
type RustlsSt = <MakeRustlsConnect as MakeTlsConnect<Socket>>::Stream;

// ---------------------------------------------------------------------------
// PgTlsConnector  (implements MakeTlsConnect)
// ---------------------------------------------------------------------------

/// A PostgreSQL TLS connector that dispatches between plain and rustls connections.
///
/// Use [`make_pg_tls`] to construct an instance from a connection string.
#[derive(Clone)]
pub enum PgTlsConnector {
    /// No TLS -- used when `sslmode=disable` or no `sslmode` is present.
    Plain,
    /// Rustls-backed TLS.
    Rustls(MakeRustlsConnect),
}

impl MakeTlsConnect<Socket> for PgTlsConnector {
    type Stream = PgTlsStream;
    type TlsConnect = PgTlsConnectInner;
    type Error = Box<dyn StdError + Sync + Send>;

    fn make_tls_connect(&mut self, domain: &str) -> Result<Self::TlsConnect, Self::Error> {
        match self {
            PgTlsConnector::Plain => Ok(PgTlsConnectInner::Plain(NoTls)),
            PgTlsConnector::Rustls(inner) => {
                <MakeRustlsConnect as MakeTlsConnect<Socket>>::make_tls_connect(inner, domain)
                    .map(PgTlsConnectInner::Rustls)
                    .map_err(|e| Box::new(e) as Box<dyn StdError + Sync + Send>)
            }
        }
    }
}

// ---------------------------------------------------------------------------
// PgTlsConnectInner  (implements TlsConnect)
// ---------------------------------------------------------------------------

/// Inner connector returned by [`PgTlsConnector::make_tls_connect`].
pub enum PgTlsConnectInner {
    Plain(NoTls),
    Rustls(RustlsTc),
}

impl TlsConnect<Socket> for PgTlsConnectInner {
    type Stream = PgTlsStream;
    type Error = Box<dyn StdError + Sync + Send>;
    type Future = PgTlsFuture;

    fn connect(self, stream: Socket) -> Self::Future {
        match self {
            PgTlsConnectInner::Plain(inner) => PgTlsFuture(Box::pin(async move {
                match inner.connect(stream).await {
                    Ok(s) => Ok(PgTlsStream::Plain(s)),
                    Err(e) => Err(Box::new(e) as Box<dyn StdError + Sync + Send>),
                }
            })),
            PgTlsConnectInner::Rustls(inner) => PgTlsFuture(Box::pin(async move {
                match inner.connect(stream).await {
                    Ok(s) => Ok(PgTlsStream::Rustls(Box::new(s))),
                    Err(e) => Err(Box::new(e) as Box<dyn StdError + Sync + Send>),
                }
            })),
        }
    }
}

// ---------------------------------------------------------------------------
// PgTlsFuture
// ---------------------------------------------------------------------------

type BoxTlsFuture =
    Pin<Box<dyn Future<Output = Result<PgTlsStream, Box<dyn StdError + Sync + Send>>> + Send>>;

/// Boxed future for the TLS connect handshake.
pub struct PgTlsFuture(BoxTlsFuture);

impl Future for PgTlsFuture {
    type Output = Result<PgTlsStream, Box<dyn StdError + Sync + Send>>;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        self.0.as_mut().poll(cx)
    }
}

// ---------------------------------------------------------------------------
// PgTlsStream  (implements TlsStream + AsyncRead + AsyncWrite)
// ---------------------------------------------------------------------------

/// Stream type that is either a plain pass-through or a rustls-encrypted stream.
pub enum PgTlsStream {
    Plain(NoTlsStream),
    Rustls(Box<RustlsSt>),
}

impl AsyncRead for PgTlsStream {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        match self.get_mut() {
            PgTlsStream::Plain(s) => Pin::new(s).poll_read(cx, buf),
            PgTlsStream::Rustls(s) => Pin::new(s).poll_read(cx, buf),
        }
    }
}

impl AsyncWrite for PgTlsStream {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &[u8],
    ) -> Poll<io::Result<usize>> {
        match self.get_mut() {
            PgTlsStream::Plain(s) => Pin::new(s).poll_write(cx, buf),
            PgTlsStream::Rustls(s) => Pin::new(s).poll_write(cx, buf),
        }
    }

    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        match self.get_mut() {
            PgTlsStream::Plain(s) => Pin::new(s).poll_flush(cx),
            PgTlsStream::Rustls(s) => Pin::new(s).poll_flush(cx),
        }
    }

    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<io::Result<()>> {
        match self.get_mut() {
            PgTlsStream::Plain(s) => Pin::new(s).poll_shutdown(cx),
            PgTlsStream::Rustls(s) => Pin::new(s).poll_shutdown(cx),
        }
    }
}

impl TlsStream for PgTlsStream {
    fn channel_binding(&self) -> ChannelBinding {
        match self {
            PgTlsStream::Plain(s) => s.channel_binding(),
            PgTlsStream::Rustls(s) => s.channel_binding(),
        }
    }
}

// ---------------------------------------------------------------------------
// Public constructor
// ---------------------------------------------------------------------------

/// Build a [`PgTlsConnector`] by inspecting the `sslmode` parameter in the
/// connection string.
///
/// * `sslmode=disable` or no `sslmode` present -- returns [`PgTlsConnector::Plain`]
/// * Any other `sslmode` value (`prefer`, `require`, ...) -- loads system root
///   certificates via `rustls-native-certs` and returns [`PgTlsConnector::Rustls`]
pub fn make_pg_tls(connection_string: &str) -> anyhow::Result<PgTlsConnector> {
    let ssl_mode = parse_ssl_mode(connection_string);
    match ssl_mode {
        Some("disable") | None => {
            info!(sslmode = ssl_mode, "postgres TLS disabled");
            Ok(PgTlsConnector::Plain)
        }
        Some(mode) => {
            info!(
                sslmode = mode,
                "postgres TLS enabled, loading system certificates"
            );
            let cert_result = rustls_native_certs::load_native_certs();
            if !cert_result.errors.is_empty() {
                tracing::warn!(
                    error_count = cert_result.errors.len(),
                    "some system certificates could not be loaded"
                );
            }
            let mut root_store = rustls::RootCertStore::empty();
            let (added, _skipped) = root_store.add_parsable_certificates(cert_result.certs);
            anyhow::ensure!(added > 0, "no usable system root certificates found");
            info!(root_certs = added, "loaded system root certificates");

            let tls_config = rustls::ClientConfig::builder()
                .with_root_certificates(root_store)
                .with_no_client_auth();
            Ok(PgTlsConnector::Rustls(MakeRustlsConnect::new(tls_config)))
        }
    }
}

/// Extract the `sslmode` value from a connection string, if present.
///
/// Handles both key-value (`host=... sslmode=require`) and URL
/// (`postgres://...?sslmode=require`) formats.
fn parse_ssl_mode(connection_string: &str) -> Option<&str> {
    // Key-value format: `sslmode=<value>` separated by whitespace
    for token in connection_string.split_whitespace() {
        if let Some(value) = token.strip_prefix("sslmode=") {
            return Some(value);
        }
    }

    // URL format: ?sslmode=<value> or &sslmode=<value>
    if let Some(query_start) = connection_string.find('?') {
        let query = &connection_string[query_start + 1..];
        for param in query.split('&') {
            if let Some(value) = param.strip_prefix("sslmode=") {
                return Some(value);
            }
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_ssl_mode_key_value() {
        assert_eq!(
            parse_ssl_mode("host=localhost sslmode=require dbname=test"),
            Some("require")
        );
    }

    #[test]
    fn parse_ssl_mode_url() {
        assert_eq!(
            parse_ssl_mode("postgres://user:pass@host/db?sslmode=require"),
            Some("require")
        );
    }

    #[test]
    fn parse_ssl_mode_url_multiple_params() {
        assert_eq!(
            parse_ssl_mode("postgres://host/db?connect_timeout=5&sslmode=prefer"),
            Some("prefer")
        );
    }

    #[test]
    fn parse_ssl_mode_disable() {
        assert_eq!(
            parse_ssl_mode("host=localhost sslmode=disable"),
            Some("disable")
        );
    }

    #[test]
    fn parse_ssl_mode_absent() {
        assert_eq!(parse_ssl_mode("host=localhost dbname=test"), None);
    }

    #[test]
    fn make_pg_tls_plain_when_no_sslmode() {
        let connector = make_pg_tls("host=localhost dbname=test").unwrap();
        assert!(matches!(connector, PgTlsConnector::Plain));
    }

    #[test]
    fn make_pg_tls_plain_when_disabled() {
        let connector = make_pg_tls("host=localhost sslmode=disable").unwrap();
        assert!(matches!(connector, PgTlsConnector::Plain));
    }
}
