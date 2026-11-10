"""TensorFlow dans WAMA : le service qui le charge pour tous, et son repli hors de la carte.

`service.py` (uvicorn, 127.0.0.1:8004), `service_client.py` (ce que tout le monde appelle),
`engine.py` (le même moteur des deux côtés), `runtime.py` (la préparation du processus). Pourquoi un
service délimité par son MOTEUR : `docs/construction/architecture/WAMA_MANIFEST_SPEC.md §7.1`.
"""
