from model_backends.factory import BackendProfile, create_backend_app

app = create_backend_app(
    BackendProfile(
        name="medium-model",
        base_latency_ms=95,
        jitter_ms=35,
        error_rate=0.02,
        max_concurrency=20,
        cost_weight=1.8,
    )
)
