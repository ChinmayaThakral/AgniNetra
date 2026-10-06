"""Community labelling holds its rules: Google must confirm each sign in, qualifying needs
real solves within the clue limit and cannot be gamed by replaying or restarting, Swipe is
closed until then, every site takes one answer per player, and abuse is throttled."""

import json

import pytest

from apps.live import community as cm

SECRET = "s" * 64
CLIENT = "client-123.apps.googleusercontent.com"
CHOICES = ["coal mine", "power plant", "other industry"]


def clues(n: int = 6) -> list[dict]:
    return [{"kind": "state", "value": f"clue {i}"} for i in range(n)]


def make(tmp_path, *, puzzles: int = 60, clock=None) -> cm.Community:
    pack = {
        "choices": CHOICES,
        "puzzles": [
            {"id": f"p{i}", "clues": clues(), "answer_mac": cm.mac(SECRET, f"p{i}", "coal mine")}
            for i in range(puzzles)
        ],
        "gold_macs": [cm.mac(SECRET, "gold", "g1")],
    }
    swipe = {
        "items": [
            {"id": "a1", "chip": "chips/a1.webp", "acquired": "2026-01-01", "community": True},
            {"id": "a2", "chip": "chips/a2.webp", "acquired": "2026-01-01", "community": True},
            {"id": "g1", "chip": "chips/g1.webp", "acquired": "2026-01-01", "community": True},
            {"id": "k1", "chip": "chips/k1.webp", "acquired": "2026-01-01", "community": False},
        ]
    }
    now = clock or (lambda: 1_000_000.0)

    def verify(token: str) -> dict:
        email, nonce = token.split("|")
        return {
            "aud": CLIENT,
            "iss": "accounts.google.com",
            "email_verified": "true",
            "exp": now() + 600,
            "nonce": nonce,
            "email": email,
        }

    return cm.Community(
        client_id=CLIENT,
        secret=SECRET,
        db_path=tmp_path / "c.db",
        pack=pack,
        swipe=swipe,
        verify=verify,
        clock=now,
    )


def call(c, method, path, body=None, token=None, ip="1.1.1.1"):
    headers = {"authorization": f"Bearer {token}"} if token else {}
    raw = json.dumps(body).encode() if body is not None else b""
    return c.handle(method, path, headers, raw, ip)


def sign_in(c, email="a@gmail.com", ip="1.1.1.1"):
    status, reply = call(
        c, "POST", "/api/session", {"id_token": f"{email}|n1", "nonce": "n1"}, ip=ip
    )
    assert status == 200, reply
    return reply["token"]


def solve(c, token, clues_first=0):
    _, view = call(c, "POST", "/api/qualify/start", {}, token)
    for _ in range(clues_first):
        call(c, "POST", "/api/qualify/clue", {"round": view["round"]}, token)
    return call(
        c, "POST", "/api/qualify/guess", {"round": view["round"], "answer": "coal mine"}, token
    )


def test_sign_in_needs_googles_confirmation_and_the_right_nonce(tmp_path) -> None:
    c = make(tmp_path)
    assert (
        call(c, "POST", "/api/session", {"id_token": "a@gmail.com|n1", "nonce": "other"})[0] == 401
    )
    c.verify = lambda t: {
        "aud": "someone-else",
        "iss": "accounts.google.com",
        "email_verified": "true",
        "exp": 2e9,
        "nonce": "n1",
        "email": "a@gmail.com",
    }
    assert call(c, "POST", "/api/session", {"id_token": "x", "nonce": "n1"})[0] == 401
    assert call(c, "GET", "/api/me")[0] == 401
    assert call(c, "GET", "/api/me", token="forged")[0] == 401


def test_a_round_counts_only_within_the_clue_limit(tmp_path) -> None:
    c = make(tmp_path)
    token = sign_in(c)
    _, reply = solve(c, token, clues_first=cm.MAX_CLUES - 1)
    assert reply["right"] and reply["counted"] and reply["correct"] == 1
    _, reply = solve(c, token, clues_first=cm.MAX_CLUES)
    assert reply["right"] and not reply["counted"] and reply["correct"] == 1


def test_a_hard_round_cannot_be_dodged_by_starting_again(tmp_path) -> None:
    c = make(tmp_path)
    token = sign_in(c)
    _, first = call(c, "POST", "/api/qualify/start", {}, token)
    _, again = call(c, "POST", "/api/qualify/start", {}, token)
    assert first["round"] == again["round"]


def test_no_site_is_dealt_twice_and_answers_never_leave_early(tmp_path) -> None:
    c = make(tmp_path, puzzles=3)
    token = sign_in(c)
    seen = set()
    for _ in range(3):
        _, view = call(c, "POST", "/api/qualify/start", {}, token)
        assert "answer" not in view and "answer_mac" not in json.dumps(view)
        seen.add(json.dumps(view["clues"]))
        call(
            c, "POST", "/api/qualify/guess", {"round": view["round"], "answer": "coal mine"}, token
        )
    assert call(c, "POST", "/api/qualify/start", {}, token)[0] == 409


def test_a_wrong_guess_opens_a_clue_and_the_last_one_ends_the_round(tmp_path) -> None:
    c = make(tmp_path)
    token = sign_in(c)
    _, view = call(c, "POST", "/api/qualify/start", {}, token)
    _, reply = call(
        c, "POST", "/api/qualify/guess", {"round": view["round"], "answer": "power plant"}, token
    )
    assert reply["right"] is False and len(reply["clues"]) == 2
    for _ in range(4):
        call(
            c,
            "POST",
            "/api/qualify/guess",
            {"round": view["round"], "answer": "power plant"},
            token,
        )
    _, reply = call(
        c, "POST", "/api/qualify/guess", {"round": view["round"], "answer": "power plant"}, token
    )
    assert reply["answer"] == "coal mine" and reply["attempts"] == 1 and reply["correct"] == 0


def test_swipe_opens_only_after_qualifying_and_takes_one_answer_per_site(tmp_path) -> None:
    ticks = iter(range(1_000_000, 2_000_000, 2))
    c = make(tmp_path, clock=lambda: float(next(ticks)))
    token = sign_in(c)
    assert call(c, "GET", "/api/swipe/next", token=token)[0] == 403
    for _ in range(cm.QUALIFY_NEEDED):
        solve(c, token)
    status, nxt = call(c, "GET", "/api/swipe/next", token=token)
    assert status == 200 and nxt["item"]["id"] in {"a1", "a2", "g1"} and nxt["total"] == 3
    item = nxt["item"]["id"]
    assert (
        call(
            c,
            "POST",
            "/api/swipe/answer",
            {"item": item, "answer": "industry", "kind": "coal mine"},
            token,
        )[0]
        == 200
    )
    assert (
        call(c, "POST", "/api/swipe/answer", {"item": item, "answer": "not industry"}, token)[0]
        == 409
    )
    assert (
        call(c, "POST", "/api/swipe/answer", {"item": "k1", "answer": "industry"}, token)[0] == 400
    )
    assert call(c, "POST", "/api/swipe/answer", {"item": "a2", "answer": "maybe"}, token)[0] == 400
    assert (
        call(
            c,
            "POST",
            "/api/swipe/answer",
            {"item": "a2", "answer": "not industry", "kind": "coal mine"},
            token,
        )[0]
        == 400
    )


def test_sign_in_attempts_are_throttled(tmp_path) -> None:
    c = make(tmp_path)
    codes = [
        call(c, "POST", "/api/session", {"id_token": "a@gmail.com|n1", "nonce": "n1"})[0]
        for _ in range(12)
    ]
    assert codes[: cm.LIMITS["signin"]] == [200] * cm.LIMITS["signin"] and codes[-1] == 429


def test_game_data_merges_and_follows_the_player(tmp_path) -> None:
    c = make(tmp_path)
    token = sign_in(c)
    call(
        c,
        "PUT",
        "/api/me/data",
        {"data": {"pet": {"xp": 30}, "heatle": {"2026-10-01": {"solved": True, "clue": 2}}}},
        token,
    )
    _, reply = call(
        c,
        "PUT",
        "/api/me/data",
        {"data": {"pet": {"xp": 5}, "heatle": {"2026-10-02": {"solved": False, "clue": 6}}}},
        token,
    )
    assert reply["data"]["pet"]["xp"] == 30 and len(reply["data"]["heatle"]) == 2
    assert call(c, "PUT", "/api/me/data", {"data": {"password": "x"}}, token)[0] == 400
    other = sign_in(c)
    assert call(c, "GET", "/api/me", token=other)[1]["data"]["pet"]["xp"] == 30


def test_a_player_can_delete_everything(tmp_path) -> None:
    c = make(tmp_path)
    token = sign_in(c)
    solve(c, token)
    assert call(c, "DELETE", "/api/me", token=token)[1] == {"deleted": True}
    assert call(c, "GET", "/api/me", token=token)[0] == 401
    assert c.db.execute("SELECT count(*) FROM rounds").fetchone()[0] == 0


def test_oversized_and_malformed_requests_are_refused(tmp_path) -> None:
    c = make(tmp_path)
    token = sign_in(c)
    assert (
        c.handle(
            "PUT",
            "/api/me/data",
            {"authorization": f"Bearer {token}"},
            b"x" * (cm.MAX_BODY + 1),
            "1.1.1.1",
        )[0]
        == 413
    )
    assert (
        c.handle(
            "POST", "/api/qualify/guess", {"authorization": f"Bearer {token}"}, b"[1]", "1.1.1.1"
        )[0]
        == 400
    )


@pytest.mark.parametrize("answer", CHOICES)
def test_the_answer_is_recovered_only_with_the_secret(answer) -> None:
    stored = cm.mac(SECRET, "p0", answer)
    assert cm.mac(SECRET, "p0", answer) == stored
    assert cm.mac("x" * 64, "p0", answer) != stored


def test_labels_need_enough_reliable_agreeing_voters() -> None:
    from apps.live.pipeline.community_labels import decide

    gold = {"g1"}
    rows = [(u, "g1", "industry", None) for u in (1, 2, 3)]
    rows.append((4, "g1", "not industry", None))
    rows += [(u, "x", "industry", "coal mine") for u in (1, 2, 3)] + [
        (4, "x", "not industry", None)
    ]
    rows += [(u, "y", "industry", None) for u in (1, 2)]
    rows += [(1, "z", "industry", None), (2, "z", "not industry", None), (3, "z", "unsure", None)]
    labels = {lab["item"]: lab for lab in decide(rows, gold, ["g1", "x", "y", "z"])["labels"]}
    assert set(labels) == {"x"}
    assert labels["x"]["label"] == "industry" and labels["x"]["kind"] == "coal mine"


def test_a_secret_that_does_not_match_the_pack_is_refused(tmp_path) -> None:
    with pytest.raises(ValueError):
        cm.Community(
            client_id=CLIENT,
            secret="x" * 64,
            db_path=tmp_path / "c.db",
            pack={
                "choices": CHOICES,
                "puzzles": [
                    {"id": "p0", "clues": clues(), "answer_mac": cm.mac(SECRET, "p0", "coal mine")}
                ],
                "gold_macs": [],
            },
            swipe={"items": []},
        )
