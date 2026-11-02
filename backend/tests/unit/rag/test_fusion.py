from backend.app.rag.retrieve import rrf_fuse, with_code_tokens


def test_code_tokens_are_appended_without_hyphens() -> None:
    assert with_code_tokens("Invoice INV-2026-00379 for OF-1001.") == (
        "Invoice INV-2026-00379 for OF-1001. INV202600379 OF1001"
    )
    assert with_code_tokens("no codes here") == "no codes here"


def test_rrf_rewards_items_ranked_well_in_both_lists() -> None:
    fused = rrf_fuse([["a", "b", "c"], ["c", "b", "d"]])
    # c (ranks 3 and 1) edges out b (2 and 2): 1/63 + 1/61 > 2/62. Both beat a and d,
    # which only one list found.
    assert [item for item, _ in fused] == ["c", "b", "a", "d"]
    assert fused[0][1] == 1 / 63 + 1 / 61


def test_rrf_of_one_list_keeps_its_order() -> None:
    assert [i for i, _ in rrf_fuse([["x", "y", "z"]])] == ["x", "y", "z"]
