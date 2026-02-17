"""TLS certificate generation for ragling MCP server.

Generates a self-signed Certificate Authority and server certificate
for securing SSE transport. Certificates are stored in ~/.ragling/tls/
and auto-generated on first use.
"""

from __future__ import annotations

import ipaddress
import logging
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

_CA_VALIDITY_DAYS = 3650  # ~10 years
_SERVER_VALIDITY_DAYS = 365  # 1 year
_KEY_SIZE = 2048


@dataclass(frozen=True)
class TLSConfig:
    """Paths to TLS certificate and key files."""

    ca_cert: Path
    ca_key: Path
    server_cert: Path
    server_key: Path


def ensure_tls_certs(tls_dir: Path | None = None) -> TLSConfig:
    """Generate CA and server certificates if they don't exist.

    If the server certificate exists but is expired, it is regenerated
    using the existing CA.

    Args:
        tls_dir: Directory for TLS files. Defaults to ~/.ragling/tls/.

    Returns:
        TLSConfig with paths to all certificate and key files.
    """
    if tls_dir is None:
        tls_dir = Path.home() / ".ragling" / "tls"

    tls_dir.mkdir(parents=True, exist_ok=True)

    cfg = TLSConfig(
        ca_cert=tls_dir / "ca.pem",
        ca_key=tls_dir / "ca-key.pem",
        server_cert=tls_dir / "server.pem",
        server_key=tls_dir / "server-key.pem",
    )

    if not cfg.ca_cert.exists():
        _generate_ca(cfg)

    if not cfg.server_cert.exists():
        _generate_server_cert(cfg)
    elif _is_expired(cfg.server_cert):
        logger.info("Server certificate expired, regenerating")
        _generate_server_cert(cfg)

    return cfg


def _is_expired(cert_path: Path) -> bool:
    """Check whether a PEM certificate file has expired."""
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    return datetime.now(timezone.utc) >= cert.not_valid_after_utc


def _generate_ca(cfg: TLSConfig) -> None:
    """Generate a self-signed CA certificate and private key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    now = datetime.now(timezone.utc)

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Ragling Local CA"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=_CA_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )

    _write_key(cfg.ca_key, key)
    cfg.ca_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Generated CA certificate: %s", cfg.ca_cert)


def _generate_server_cert(cfg: TLSConfig) -> None:
    """Generate a server certificate signed by the CA."""
    ca_cert = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())
    ca_key = serialization.load_pem_private_key(cfg.ca_key.read_bytes(), password=None)
    assert isinstance(ca_key, rsa.RSAPrivateKey)

    key = rsa.generate_private_key(public_exponent=65537, key_size=_KEY_SIZE)
    now = datetime.now(timezone.utc)

    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
        ]
    )

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=_SERVER_VALIDITY_DAYS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("host.docker.internal"),
                    x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    _write_key(cfg.server_key, key)
    cfg.server_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    logger.info("Generated server certificate: %s", cfg.server_cert)


def create_ssl_context(cfg: TLSConfig) -> ssl.SSLContext:
    """Create an ssl.SSLContext for the TLS server.

    Args:
        cfg: TLS certificate paths from ensure_tls_certs().

    Returns:
        Configured SSLContext for use with uvicorn or other ASGI servers.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cfg.server_cert), str(cfg.server_key))
    return ctx


def _write_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    """Write a private key to disk with restricted permissions."""
    key_bytes = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    path.write_bytes(key_bytes)
    path.chmod(0o600)
