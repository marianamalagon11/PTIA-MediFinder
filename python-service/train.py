"""
Entry point de entrenamiento. Ejecuta en orden:
1. KNN sobre el catálogo de medicamentos
2. Knowledge base del LLM (RAG)

Uso:
    python train.py           → entrena todo
    python train.py --knn     → solo KNN
    python train.py --kb      → solo knowledge base
"""

import sys
from pathlib import Path


def main():
    args = sys.argv[1:]
    solo_knn = "--knn" in args
    solo_kb  = "--kb"  in args
    todo     = not solo_knn and not solo_kb

    if todo or solo_knn:
        print("═══ Entrenando KNN ═══")
        from scripts.train_knn import main as train_knn
        train_knn()

    if todo or solo_kb:
        print("\n═══ Construyendo Knowledge Base (LLM) ═══")
        from scripts.build_knowledge_base import main as build_kb
        build_kb()

    print("\nEntrenamiento completo.")


if __name__ == "__main__":
    main()