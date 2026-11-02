from meetingroom.server import handoff_names


def test_each_sentence_can_hand_off():
    t = "@sonnet review docs. @codex fix perf. @codex-2 audit security. @sonnet-2 run tests. Report to me."
    assert handoff_names(t) == {"sonnet", "codex", "codex-2", "sonnet-2"}


def test_leading_group_and_lines():
    assert handoff_names("@sonnet, @codex: do X") == {"sonnet", "codex"}
    assert handoff_names("@sonnet and @codex do X") == {"sonnet", "codex"}
    assert handoff_names("Done.\n@codex check it\n- @sonnet plot it") == {"codex", "sonnet"}


def test_passing_mentions_ignored():
    assert handoff_names("I think @codex owns this.") == set()
    assert handoff_names("Ask Ingrid (@codex) later") == set()
    assert handoff_names("mail a@b.com") == set()
