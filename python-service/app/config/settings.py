from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""

    embeddings_dir: str = "app/data/embeddings_db"
    images_dir: str = "app/data/raw_images"
    csv_invima: str = "app/data/medicamentos_invima.csv"       
    csv_medicamentos: str = "app/data/medicamentos_detallado.csv"  
    csv_principios: str = "app/data/principios_activos.csv"
    models_dir: str = "models/medifinder"

    knn_k: int = 5
    cnn_similarity_threshold: float = 0.45
    ocr_confidence_threshold: int = 60

    class Config:
        env_file = ".env"


settings = Settings()