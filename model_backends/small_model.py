from model_backends.factory import BackendProfile, create_backend_app

app = create_backend_app(
    BackendProfile(
        name="small-model",
        base_latency_ms=45,
        jitter_ms=15,
        error_rate=0.01,
        max_concurrency=32,
        cost_weight=1.0,
    )
)
