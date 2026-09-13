"""Fonctions du STUDIO déclarées au catalogue commun (`load_all` importe ce module).

`studio.image_to_3d` — ROADMAP §17ter trou 4, la chaîne « photo de véhicule → segmentation →
reconstruction 3D → médiathèque → virtualib ». Capability-first (§16.6) : un nœud `function`
du studio, pas une app de file. `binding=APP` : l'implémentation est une tâche Celery GPU
(`studio.gpu_tasks:image_to_3d_task`) lancée puis pollée par l'exécuteur, comme les passes du
cam_analyzer — avec une différence que l'exécuteur porte depuis le 13/09 : le fichier de
l'AMONT (une image, sortie d'un nœud d'app ou d'un `media_import`) lui est passé par son port.

Les PORTS parlent le vocabulaire des types : l'entrée est une `image` (catégorie média — ce
qu'un nœud d'app produit, `category_of_path`), la sortie un `object_3d` (`DataType.OBJECT_3D`,
le type que la nature d'asset `object3d` déclare). C'est ce qui rend le nœud « Sortie » capable
de ranger le GLB en médiathèque avec ses attributs lus du fichier.
"""
from wama.common.catalog.data_types import DataType as DT
from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,
                                                  ParamSpec, PortSpec, register)

register(FunctionSpec(
    key='studio.image_to_3d',
    name='Image → objet 3D',
    description="Reconstruit un maillage 3D texturé (GLB, pivot de la médiathèque) depuis UNE image "
                "— de préférence détourée (sortie du detector / SAM3). Modèle TripoSR (MIT). "
                "⚠ PLAUSIBLE, pas métrique : les faces occultées sont hallucinées ; un prop de "
                "simulation, jamais une mesure (§17ter).",
    category=FC.TRANSFORM,
    binding=Binding.APP, app='studio',
    impl='studio.gpu_tasks:image_to_3d_task',
    tags=['vision', 'gpu', '3d', 'reconstruction', 'plausible'],
    inputs=[PortSpec('image', 'image', description="L'image source (RGB ou RGBA détourée).")],
    outputs=[PortSpec('object', DT.OBJECT_3D, produced_fields=['format', 'polygons'],
                      description='Maillage GLB coloré par sommet, rangé chez l’utilisateur '
                                  '(`users/<uid>/studio/output/`).')],
    params=[ParamSpec('resolution', 'int', 256, min=64, max=512, unit='voxels',
                      description='Résolution du marching cubes (plus fin = plus de faces, plus lent).'),
            ParamSpec('foreground_ratio', 'float', 0.85, min=0.5, max=1.0,
                      description="Part du cadre occupée par l'objet après recadrage (image RGBA)."),
            ParamSpec('model', 'str', 'huggingface:triposr',
                      description='Clé de catalogue du modèle image→3D (moteur résolu par le backend).')],
    cost={'vram_gb': 6, 'approx_s': 5},
))
