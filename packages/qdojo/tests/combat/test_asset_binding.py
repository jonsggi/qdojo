"""AdminBindAsset (opcode 103): the registry names the fighter's real Qubic asset.

The legacy AdminRegisterAsset (100) binds the interim asset (issuer =
fighter_id, name QDOJOF) that no one can issue; 103 carries the issuer and
the asset name, so a QX-issued fighter NFT can be bound (docs/nft.md §5.3).
"""
import pytest

from qdojo.combat import codec
from qdojo.combat.codec import Code, Op
from qdojo.combat.sim import identity

from .test_contract import ADMIN, world  # noqa: F401  (fixture)

ISSUER = identity("issuer")


def bind(w, fid, name="QF0001", issuer=ISSUER, who=ADMIN, version=1, npc=0, amount=0):
    value = codec.asset_name_u64(name) if isinstance(name, str) else name
    return w.send(who, Op.ADMIN_BIND_ASSET, amount, fighter_id=fid, registry_version=version, house_npc=npc,
                  asset_issuer=issuer, asset_name=value)


def test_asset_names():
    assert codec.asset_name_u64("QDOJOF") == codec.LEGACY_ASSET_NAME
    assert codec.asset_name_u64("QF0001") == int.from_bytes(b"QF0001", "little")
    for bad in ("", "qf1", "1QF", "Q-1", "QDOJOFXX", "QÄ"):
        with pytest.raises(codec.CodecError):
            codec.asset_name_u64(bad)
    assert not codec.asset_name_ok(0)
    assert not codec.asset_name_ok(int.from_bytes(b"A\0B", "little"))     # a gap is not padding
    assert not codec.asset_name_ok(int.from_bytes(b"ABCDEFGH", "little"))  # eight characters


def test_bind_then_register_and_event_body(world):  # noqa: F811
    fid, owner = identity("fighter:nft"), identity("owner:nft")
    world.owners[fid] = owner
    world.mint(owner, 10_000)
    assert bind(world, fid).ok
    c = world.contract
    assert c.assets[fid] == (1, False, ISSUER, codec.asset_name_u64("QF0001"))
    seq, _, kind, fields, _ = c.events[-1]
    assert kind == "ASSET_REGISTERED" and fields == (fid, 1, 0, ISSUER, codec.asset_name_u64("QF0001"))
    assert world.send(owner, Op.REGISTER_FIGHTER, fighter_id=fid, registry_version=1).ok
    assert c.fighters[fid].owner == owner
    world.check_conservation()


def test_bind_rejections(world):  # noqa: F811
    fid, other = identity("fighter:a"), identity("fighter:b")
    assert bind(world, fid, who=identity("stranger")).code == Code.NOT_OWNER
    assert bind(world, fid, issuer=bytes(32)).code == Code.BAD_BODY
    assert bind(world, fid, name=0).code == Code.BAD_BODY
    assert bind(world, fid, name=int.from_bytes(b"qf1", "little")).code == Code.BAD_BODY
    assert bind(world, fid, npc=2).code == Code.BAD_BODY
    assert bind(world, fid, amount=5).code == Code.BAD_AMOUNT
    assert bind(world, fid).ok
    # One asset never backs two fighters; the same fighter may be rebound.
    assert bind(world, other).code == Code.BAD_STATE
    assert bind(world, other, name="QF0002").ok
    assert bind(world, fid, name="QF0003", version=2).ok
    assert bind(world, other, name="QF0001").ok
    # The legacy opcode binds (fighter_id, QDOJOF) and refuses an asset bound elsewhere.
    assert bind(world, other, name="QDOJOF", issuer=fid).ok
    assert world.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=0).code \
        == Code.BAD_STATE
    world.check_conservation()


def test_legacy_register_asset_is_unchanged(world):  # noqa: F811
    fid = identity("fighter:legacy")
    assert world.send(ADMIN, Op.ADMIN_REGISTER_ASSET, fighter_id=fid, registry_version=1, house_npc=1).ok
    c = world.contract
    assert c.assets[fid] == (1, True, fid, codec.LEGACY_ASSET_NAME)
    assert c.events[-1][3] == (fid, 1, 1)     # three fields: old journals keep their digests
