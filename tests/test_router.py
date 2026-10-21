from jarvis.brain.router import BrainRouter, TaskType


def test_classify_fast_by_default():
    router = BrainRouter(config={})
    assert router.classify("what time is it") == TaskType.FAST


def test_classify_code_hint():
    router = BrainRouter(config={})
    assert router.classify("can you refactor this function") == TaskType.CODE


def test_classify_vision_hint():
    router = BrainRouter(config={})
    assert router.classify("what's on my screen right now") == TaskType.VISION


def test_route_maps_task_to_provider():
    router = BrainRouter(config={})
    assert router.route(TaskType.FAST) == "gemini"
    assert router.route(TaskType.CODE) == "claude"
    assert router.route(TaskType.VISION) == "gemini"
    assert router.route(TaskType.OFFLINE) == "ollama"


def test_offline_mode_forces_ollama():
    router = BrainRouter(config={}, offline=True)
    assert router.classify("refactor my code") == TaskType.OFFLINE
    assert router.route(router.classify("anything")) == "ollama"


def test_model_for_reads_config():
    router = BrainRouter(config={"llm": {"models": {"fast": "llama-3.3-70b-versatile"}}})
    assert router.model_for(TaskType.FAST) == "llama-3.3-70b-versatile"
    assert router.model_for(TaskType.CODE) is None


def test_route_utterance_combines_classify_and_route():
    router = BrainRouter(config={"llm": {"models": {"code": "claude-3-5-sonnet"}}})
    provider, model = router.route_utterance("please debug this bug")
    assert provider == "claude"
    assert model == "claude-3-5-sonnet"
