from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    wifi_ssid: str = ""
    wifi_password: str = ""
    wifi_interface: str = "wlan1"
    camera_ip: str = "192.168.122.1"
    camera_port: str = "64321"
    output_dir: str = "/data/photos"

    webapp_username: str = ""
    webapp_password: str = ""
    webapp_secret_key: str = ""

    # Sync without pressing Pair: every interval, check if the camera's AP is in
    # range and sync when it is. Floor of 10s since each check scans the adapter.
    auto_scan_enabled: bool = False
    auto_scan_interval_seconds: int = Field(default=60, ge=10)

    # Optional. Gets a message when a sync starts transferring and when it ends.
    webhook_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
