from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    wifi_ssid: str = ""
    wifi_password: str = ""
    wifi_interface: str = "wlan1"
    camera_ip: str = "192.168.122.1"
    camera_port: str = "64321"
    output_dir: str = "/data/photos"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
