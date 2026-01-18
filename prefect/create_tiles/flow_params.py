
from typing import Literal
from typing_extensions import TypedDict
from pydantic import Field

class MapSize(TypedDict):
    x: int = Field(512, description="X方向のマップサイズ(タイル数)")
    y: int = Field(512, description="Y方向のマップサイズ(タイル数)")

class CaptureConfig(TypedDict):
    crop_offset_x: int = Field(128, description="撮影時の左右クロップ幅(px)")
    crop_offset_y: int = Field(64, description="撮影時の上下クロップ高さ(px)")
    margin_width: int = Field(160, description="画像の左右のりしろ幅(px)")
    margin_height: int = Field(80, description="画像の上下のりしろ高さ(px)")
    effective_width: int = Field(3200, description="画像ののりしろを除いた有効幅(px)")
    effective_height: int = Field(1600, description="画像ののりしろを除いた有効高さ(px)")

    def image_width(self) -> int:
        return self['effective_width'] + self['margin_width'] * 2

    def image_height(self) -> int:
        return self['effective_height'] + self['margin_height'] * 2

    def capture_width(self) -> int:
        image_width = self.image_width()
        return image_width + self['crop_offset_x'] * 2

    def capture_height(self) -> int:
        image_height = self.image_height()
        return image_height + self['crop_offset_y'] * 2

ZoomLevel = Literal[
    "one_eighth",
    "quarter",
    "half",
    "normal",
    "double",
]

TileQuality = int | Literal["lossless"]

class CreateTilesParams(TypedDict):
    folder_path: str
    binary_name: str
    pakset_name: str
    paksize: int
    save_data_name: str
    map_size: MapSize
    zoom_level: ZoomLevel
    tile_size: int
    tile_quality_max_zoom: TileQuality
    tile_quality_other: TileQuality
    tile_group_size: int
    delta: int
    capture_redraw_wait_seconds: float
    capture: CaptureConfig

    def adjusted_paksize(self) -> int:
        zoom_level_map = {
            "one_eighth": 0.125,
            "quarter": 0.25,
            "half": 0.5,
            "normal": 1.0,
            "double": 2.0,
        }
        return int(self.paksize * zoom_level_map[self.zoom_level])

    def full_width(self) -> int:
        adjusted_paksize = self.adjusted_paksize()
        return (adjusted_paksize // 2) * (self.map_size['width'] + self.map_size['height']) + self.capture['margin_width'] * 4

    def full_height(self) -> int:
        adjusted_paksize = self.adjusted_paksize()
        return (adjusted_paksize // 4) * (self.map_size['width'] + self.map_size['height']) + self.capture['margin_height'] * 2

    def max_z(self) -> int:
        return math.ceil(math.log2(max(self.full_width(), self.full_height()) // self.tile_size))
