"""Ejecuta los tres modelos en CUDA con una imagen sintética; no mide navegación."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'piloto_agl'))
from comun import setup
from modelos import dino, local_models


def main():
    import torch
    setup()
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA no disponible')
    encoder = dino(device='cuda')
    extractor, matcher = local_models(device='cuda')
    with torch.inference_mode():
        embedding = encoder(torch.rand(1, 3, 224, 224, device='cuda'))
        features = extractor.extract(torch.rand(1, 1, 240, 320, device='cuda'))
        result = matcher({'image0': features, 'image1': features})
        torch.cuda.synchronize()
    if embedding.device.type != 'cuda' or not torch.isfinite(embedding).all():
        raise RuntimeError('Descriptor DINOv2 CUDA inválido')
    matches = result['matches'][0]
    if matches.device.type != 'cuda' or len(matches) == 0:
        raise RuntimeError('LightGlue no ha obtenido coincidencias CUDA en la imagen idéntica')
    proof = dict(torch=torch.__version__, cuda=torch.version.cuda,
                 gpu=torch.cuda.get_device_name(0),
                 models={name: str(next(model.parameters()).device) for name, model in
                         [('DINOv2', encoder), ('SuperPoint', extractor), ('LightGlue', matcher)]},
                 self_matches=len(matches),
                 scope='Inferencia sintética de instalación; no validación geográfica ni vuelo')
    output = ROOT / 'outputs/instalacion/modelos_cuda.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, indent=2, ensure_ascii=False), encoding='utf8')
    print(json.dumps(proof, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
