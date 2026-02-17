"""Tests for ragling.tls module — CA and server certificate generation."""

import ssl
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.x509.oid import NameOID
from ragling.tls import TLSConfig


class TestTLSConfig:
    """Tests for the TLSConfig dataclass."""

    def test_tls_config_holds_paths(self, tmp_path: Path) -> None:
        from ragling.tls import TLSConfig

        cfg = TLSConfig(
            ca_cert=tmp_path / "ca.pem",
            ca_key=tmp_path / "ca-key.pem",
            server_cert=tmp_path / "server.pem",
            server_key=tmp_path / "server-key.pem",
        )
        assert cfg.ca_cert == tmp_path / "ca.pem"
        assert cfg.ca_key == tmp_path / "ca-key.pem"
        assert cfg.server_cert == tmp_path / "server.pem"
        assert cfg.server_key == tmp_path / "server-key.pem"


class TestEnsureTLSCerts:
    """Tests for ensure_tls_certs() orchestration."""

    def test_generates_all_four_files(self, tmp_path: Path) -> None:
        """First call generates CA cert, CA key, server cert, server key."""
        from ragling.tls import ensure_tls_certs

        tls_dir = tmp_path / "tls"
        cfg = ensure_tls_certs(tls_dir)

        assert cfg.ca_cert.exists()
        assert cfg.ca_key.exists()
        assert cfg.server_cert.exists()
        assert cfg.server_key.exists()

    def test_creates_tls_directory(self, tmp_path: Path) -> None:
        """tls_dir is created if it doesn't exist."""
        from ragling.tls import ensure_tls_certs

        tls_dir = tmp_path / "nested" / "tls"
        ensure_tls_certs(tls_dir)

        assert tls_dir.is_dir()

    def test_idempotent_does_not_regenerate(self, tmp_path: Path) -> None:
        """Calling ensure_tls_certs twice keeps the same files."""
        from ragling.tls import ensure_tls_certs

        tls_dir = tmp_path / "tls"
        cfg1 = ensure_tls_certs(tls_dir)
        ca_mtime = cfg1.ca_cert.stat().st_mtime
        server_mtime = cfg1.server_cert.stat().st_mtime

        cfg2 = ensure_tls_certs(tls_dir)
        assert cfg2.ca_cert.stat().st_mtime == ca_mtime
        assert cfg2.server_cert.stat().st_mtime == server_mtime

    def test_private_key_permissions(self, tmp_path: Path) -> None:
        """Private key files must have 0o600 permissions."""
        from ragling.tls import ensure_tls_certs

        tls_dir = tmp_path / "tls"
        cfg = ensure_tls_certs(tls_dir)

        ca_key_mode = cfg.ca_key.stat().st_mode & 0o777
        server_key_mode = cfg.server_key.stat().st_mode & 0o777
        assert ca_key_mode == 0o600, f"CA key perms: {oct(ca_key_mode)}"
        assert server_key_mode == 0o600, f"Server key perms: {oct(server_key_mode)}"

    def test_default_tls_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Default tls_dir is ~/.ragling/tls/."""
        from ragling.tls import ensure_tls_certs

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        cfg = ensure_tls_certs()

        assert cfg.ca_cert.parent == tmp_path / ".ragling" / "tls"


class TestCAGeneration:
    """Tests for CA certificate properties."""

    def test_ca_is_self_signed(self, tmp_path: Path) -> None:
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        ca = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())

        assert ca.issuer == ca.subject

    def test_ca_has_correct_cn(self, tmp_path: Path) -> None:
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        ca = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())

        cn = ca.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert "ragling" in cn.lower()

    def test_ca_valid_10_years(self, tmp_path: Path) -> None:
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        ca = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())

        now = datetime.now(timezone.utc)
        validity_days = (ca.not_valid_after_utc - now).days
        # Should be approximately 10 years (3650 days), allow some margin
        assert 3640 <= validity_days <= 3660

    def test_ca_is_ca(self, tmp_path: Path) -> None:
        """CA cert has BasicConstraints CA=True."""
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        ca = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())

        bc = ca.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True


class TestServerCertGeneration:
    """Tests for server certificate properties."""

    def test_server_signed_by_ca(self, tmp_path: Path) -> None:
        """Server cert is signed by the CA, not self-signed."""
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        ca = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())
        server = x509.load_pem_x509_certificate(cfg.server_cert.read_bytes())

        assert server.issuer == ca.subject
        assert server.subject != server.issuer

    def test_server_valid_1_year(self, tmp_path: Path) -> None:
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        server = x509.load_pem_x509_certificate(cfg.server_cert.read_bytes())

        now = datetime.now(timezone.utc)
        validity_days = (server.not_valid_after_utc - now).days
        assert 360 <= validity_days <= 370

    def test_server_san_includes_localhost(self, tmp_path: Path) -> None:
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        server = x509.load_pem_x509_certificate(cfg.server_cert.read_bytes())

        san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert "localhost" in dns_names

    def test_server_san_includes_127_0_0_1(self, tmp_path: Path) -> None:
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        server = x509.load_pem_x509_certificate(cfg.server_cert.read_bytes())

        san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        ip_addrs = [str(ip) for ip in san.value.get_values_for_type(x509.IPAddress)]
        assert "127.0.0.1" in ip_addrs

    def test_server_is_not_ca(self, tmp_path: Path) -> None:
        """Server cert must NOT be a CA."""
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        server = x509.load_pem_x509_certificate(cfg.server_cert.read_bytes())

        bc = server.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is False


class TestServerCertRenewal:
    """Tests for expired server cert auto-renewal."""

    def test_expired_server_cert_is_regenerated(self, tmp_path: Path) -> None:
        """When server cert exists but is expired, ensure_tls_certs regenerates it."""
        from ragling.tls import ensure_tls_certs

        tls_dir = tmp_path / "tls"
        cfg = ensure_tls_certs(tls_dir)

        # Record original CA mtime (should NOT change)
        ca_mtime = cfg.ca_cert.stat().st_mtime

        # Overwrite server cert with an expired one
        _write_expired_cert(cfg)

        # Re-run — should regenerate server cert but keep CA
        cfg2 = ensure_tls_certs(tls_dir)
        server = x509.load_pem_x509_certificate(cfg2.server_cert.read_bytes())

        now = datetime.now(timezone.utc)
        assert server.not_valid_after_utc > now
        assert cfg2.ca_cert.stat().st_mtime == ca_mtime


class TestCreateSSLContext:
    """Tests for create_ssl_context() helper."""

    def test_returns_server_ssl_context(self, tmp_path: Path) -> None:
        from ragling.tls import create_ssl_context, ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")
        ctx = create_ssl_context(cfg)

        assert isinstance(ctx, ssl.SSLContext)


class TestTLSHandshake:
    """Integration test: verify certs actually work for a TLS handshake."""

    def test_ssl_context_loads_certs(self, tmp_path: Path) -> None:
        """ssl.SSLContext can load the generated server cert chain."""
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(cfg.server_cert), str(cfg.server_key))
        # No exception means success

    def test_client_verifies_with_ca(self, tmp_path: Path) -> None:
        """A client context trusting the CA can verify the server cert."""
        from ragling.tls import ensure_tls_certs

        cfg = ensure_tls_certs(tmp_path / "tls")

        client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_ctx.load_verify_locations(str(cfg.ca_cert))
        # No exception means the CA is loadable as a trust anchor


def _write_expired_cert(cfg: TLSConfig) -> None:
    """Helper: overwrite server cert with one that expired yesterday."""
    from datetime import timedelta

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    ca_cert = x509.load_pem_x509_certificate(cfg.ca_cert.read_bytes())
    ca_key = serialization.load_pem_private_key(cfg.ca_key.read_bytes(), password=None)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=400))
        .not_valid_after(now - timedelta(days=1))
        .sign(ca_key, hashes.SHA256())
    )

    cfg.server_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cfg.server_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
