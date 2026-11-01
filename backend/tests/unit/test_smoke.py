def test_packages_import() -> None:
    import backend.app.domain
    import data_generator

    assert backend.app.domain is not None
    assert data_generator is not None
