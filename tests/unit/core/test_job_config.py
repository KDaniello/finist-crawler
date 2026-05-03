from core.job_config import JobConfig


class TestJobConfigDefaults:
    def test_default_values(self):
        cfg = JobConfig()
        assert cfg.spec_name == ""
        assert cfg.max_pages == 5
        assert cfg.detail_max_pages == 0
        assert cfg.template_params == {}
        assert cfg.direct_urls == []


class TestToDict:
    def test_to_dict(self):
        cfg = JobConfig(
            spec_name="test.yaml",
            max_pages=10,
            detail_max_pages=5,
            template_params={"keyword": "python"},
            direct_urls=["http://example.com"],
        )
        result = cfg.to_dict()
        assert result == {
            "max_pages": 10,
            "detail_max_pages": 5,
            "template_params": {"keyword": "python"},
            "direct_urls": ["http://example.com"],
        }


class TestFromDict:
    def test_from_dict_full(self):
        overrides = {
            "max_pages": 20,
            "detail_max_pages": 3,
            "template_params": {"q": "test"},
            "direct_urls": ["http://a.com"],
        }
        cfg = JobConfig.from_dict("my_spec.yaml", overrides)
        assert cfg.spec_name == "my_spec.yaml"
        assert cfg.max_pages == 20
        assert cfg.detail_max_pages == 3
        assert cfg.template_params == {"q": "test"}
        assert cfg.direct_urls == ["http://a.com"]

    def test_from_dict_partial(self):
        cfg = JobConfig.from_dict("spec.yaml", {"max_pages": 1})
        assert cfg.spec_name == "spec.yaml"
        assert cfg.max_pages == 1
        assert cfg.detail_max_pages == 0
        assert cfg.template_params == {}
        assert cfg.direct_urls == []

    def test_from_dict_empty(self):
        cfg = JobConfig.from_dict("spec.yaml", {})
        assert cfg.max_pages == 5
