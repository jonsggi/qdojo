"""Qubic itself, in Python: hashing, keys, signatures, transactions, the node.

qdojo used to reach the chain through a compiled qubic-cli that every bot
author had to build first. Everything that binary did for us is here instead:
KangarooTwelve, FourQ, SchnorrQ, the identity encoding, the transaction
format and the node's TCP protocol. A fighter now needs Python and nothing
else, and a seed never has to be written to a file for another process to
read.

Trust in this code does not rest on it being tidy. `scripts/crosscheck-signer.py`
signs real transactions with both this package and the reference qubic-cli
and compares every byte; the same harness proved it over 2,316 identities and
84 transactions before it was wired in. Run it after touching anything here.
"""
from .fourq import decode, encode, scalar_mul                     # noqa: F401
from .ids import (                                                # noqa: F401
    IDENTITY_LEN,
    PUBLIC_DEFAULT_IDENTITY,
    SEED_LEN,
    check_identity,
    identity_from_public_key,
    identity_from_seed,
    keys_from_seed,
    private_key_from_subseed,
    public_key_from_identity,
    public_key_from_private_key,
    subseed_from_seed,
    tx_hash_from_digest,
)
from .k12 import k12                                              # noqa: F401
from .node import Node, NodeError                                 # noqa: F401
from .schnorrq import sign, verify                                # noqa: F401
from .tx import SignedTransaction, Transaction                    # noqa: F401
