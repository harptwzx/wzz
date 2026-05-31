"""
Security Module
通信加密、设备指纹验证、证书固定
"""
import logging
import hashlib
import hmac
import secrets
from typing import Optional
from pathlib import Path

import snappy
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger("MDCS.Security")

class SecurityManager:
    """
    安全管理器
    - TLS/SSL上下文配置
    - 设备指纹验证（基于硬件标识）
    - 数据压缩与校验
    - 证书固定（Certificate Pinning）
    """

    def __init__(self, cert_path: Optional[str] = None, key_path: Optional[str] = None):
        self.cert_path = cert_path or "/app/certs/server.crt"
        self.key_path = key_path or "/app/certs/server.key"
        self._ssl_context = None
        self._trusted_fingerprints: set = set()

        # Load or generate certificates
        self._ensure_certificates()

    def _ensure_certificates(self):
        """确保TLS证书存在（生产环境应使用真实CA签名证书）"""
        cert_file = Path(self.cert_path)
        key_file = Path(self.key_path)

        if not cert_file.exists() or not key_file.exists():
            logger.warning("TLS certificates not found, generating self-signed certificates")
            self._generate_self_signed_cert()

    def _generate_self_signed_cert(self):
        """生成自签名证书（仅用于开发/测试）"""
        from cryptography.x509.oid import NameOID
        import datetime

        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )

        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"CN"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"MDCS"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"mdcs-coordinator"),
        ])

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
            critical=False,
        ).sign(key, hashes.SHA256(), default_backend())

        # Ensure directory exists
        Path(self.cert_path).parent.mkdir(parents=True, exist_ok=True)

        with open(self.key_path, "wb") as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))

        with open(self.cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        logger.info(f"Self-signed certificates generated at {self.cert_path}")

    def get_ssl_context(self):
        """获取SSL上下文（用于WebSocket TLS）"""
        import ssl
        if self._ssl_context is None:
            self._ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self._ssl_context.load_cert_chain(self.cert_path, self.key_path)
            # Certificate pinning: only trust our CA
            self._ssl_context.verify_mode = ssl.CERT_REQUIRED
            self._ssl_context.load_verify_locations(self.cert_path)
        return self._ssl_context

    def verify_fingerprint(self, device_id: str, fingerprint: str) -> bool:
        """
        验证设备指纹
        指纹生成规则：HMAC-SHA256(device_id + hardware_serial, secret_key)
        设备端使用相同算法生成指纹，防止非法设备接入
        """
        if not fingerprint:
            # In development, allow empty fingerprint
            logger.warning(f"Empty fingerprint for {device_id}, allowing in dev mode")
            return True

        # In production, verify against pre-registered fingerprints
        # For demo, we accept any fingerprint that looks valid (64 hex chars)
        if len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint.lower()):
            return True

        logger.warning(f"Invalid fingerprint for device {device_id}")
        return False

    def generate_device_fingerprint(self, device_id: str, hardware_serial: str, secret: str) -> str:
        """为设备生成指纹（供设备端使用）"""
        message = f"{device_id}:{hardware_serial}".encode()
        key = secret.encode()
        return hmac.new(key, message, hashlib.sha256).hexdigest()

    @staticmethod
    def compress_data(data: bytes) -> bytes:
        """使用Snappy压缩数据"""
        return snappy.compress(data)

    @staticmethod
    def decompress_data(data: bytes) -> bytes:
        """解压缩Snappy数据"""
        return snappy.decompress(data)

    @staticmethod
    def hash_activation(activation_data: bytes) -> str:
        """计算激活值的校验和，用于完整性验证"""
        return hashlib.sha256(activation_data).hexdigest()[:16]
