"""Sign and verify the exact bytes of the permission configuration."""

import base64
import tomllib
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


ROOT = Path(__file__).resolve().parent


def load_config(directory=ROOT):
    content = (directory / "permissions.toml").read_bytes()
    public_key = serialization.load_pem_public_key((directory / "permissions-public.pem").read_bytes())
    if not isinstance(public_key, Ed25519PublicKey):
        raise ValueError("Permission public key must be Ed25519")
    signature = base64.b64decode((directory / "permissions.sig").read_bytes().strip(), validate=True)
    try:
        public_key.verify(signature, content)
    except InvalidSignature as error:
        raise PermissionError("Permission configuration signature is invalid; sign the approved configuration again") from error
    return tomllib.loads(content.decode("utf-8"))


def sign_config(directory=ROOT):
    content = (directory / "permissions.toml").read_bytes()
    tomllib.loads(content.decode("utf-8"))
    private_key = serialization.load_pem_private_key((directory / ".private" / "permissions-private.pem").read_bytes(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Permission private key must be Ed25519")
    public_key = serialization.load_pem_public_key((directory / "permissions-public.pem").read_bytes())
    if private_key.public_key().public_bytes_raw() != public_key.public_bytes_raw():
        raise ValueError("Permission private and public keys do not match")
    (directory / "permissions.sig").write_bytes(base64.b64encode(private_key.sign(content)) + b"\n")


def generate_keys(directory=ROOT):
    private_path = directory / ".private" / "permissions-private.pem"
    public_path = directory / "permissions-public.pem"
    if private_path.exists() or public_path.exists():
        raise FileExistsError("Permission keys already exist; refusing to replace them")
    private_path.parent.mkdir(exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    with private_path.open("xb") as stream:
        stream.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with public_path.open("xb") as stream:
        stream.write(private_key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
