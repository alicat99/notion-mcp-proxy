import argparse

from signed_config import generate_keys, load_config, sign_config


def main():
    parser = argparse.ArgumentParser(description="Sign the approved permissions.toml with the local private key")
    parser.add_argument("--init", action="store_true", help="Generate keys before signing; refuses to overwrite existing keys")
    parser.add_argument("--verify", action="store_true", help="Verify only; no private key required")
    options = parser.parse_args()
    if options.init and options.verify:
        parser.error("--init and --verify cannot be combined")
    if options.init:
        generate_keys()
    if not options.verify:
        sign_config()
    load_config()
    print("Permission configuration signature verified.")


if __name__ == "__main__":
    main()
