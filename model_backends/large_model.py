from model_backends.factory import BackendProfile, create_backend_app

app = create_backend_app(
    BackendProfile(
        name="large-model",
        base_latency_ms=180,
        jitter_ms=70,
        error_rate=0.04,
        max_concurrency=12,
        cost_weight=3.0,
    )
)
