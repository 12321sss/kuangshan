import { WebMapTileServiceImageryProvider, UrlTemplateImageryProvider, Credit } from 'cesium'
import { TIANDITU_TOKEN } from '@/config'

/**
 * 天地图 WMTS 影像提供器（已实测排错后的正确配置）
 * 关键点：Cesium 第 L 级对应天地图 TileMatrix=L，不要配 tileMatrixLabels（会错位一级）；
 * 天地图没有 0 级矩阵，minimumLevel 必须从 1 开始。
 *
 * @param layer img=影像底图 / vec=矢量底图 / cia=影像注记 / cva=矢量注记
 */
export function tiandituProvider(layer: 'img' | 'vec' | 'cia' | 'cva') {
  return new WebMapTileServiceImageryProvider({
    url:
      `https://t{s}.tianditu.gov.cn/${layer}_w/wmts` +
      '?service=wmts&request=GetTile&version=1.0.0' +
      `&LAYER=${layer}&tileMatrixSet=w` +
      '&TileMatrix={TileMatrix}&TileRow={TileRow}&TileCol={TileCol}' +
      '&style=default&format=tiles&tk=' + TIANDITU_TOKEN,
    subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'],
    layer,
    style: 'default',
    format: 'tiles',
    tileMatrixSetID: 'w',
    minimumLevel: 1,
    maximumLevel: 18,
    credit: new Credit('天地图')
  })
}

/** 底图组合：影像=img+cia 注记；矢量=vec+cva 注记 */
export function tiandituBaseLayers(kind: 'img' | 'vec') {
  return kind === 'img'
    ? { base: tiandituProvider('img'), label: tiandituProvider('cia') }
    : { base: tiandituProvider('vec'), label: tiandituProvider('cva') }
}

/**
 * 高德卫星影像（备用底图）：无需 token，国内直连稳定。
 * 注意：高德瓦片是 GCJ-02 偏移坐标系，与 WGS84 传感器坐标有数百米偏差，仅作视觉参考底图。
 */
export function gaodeSatelliteProvider() {
  return new UrlTemplateImageryProvider({
    url: 'https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}',
    subdomains: ['1', '2', '3', '4'],
    maximumLevel: 18,
    credit: new Credit('高德地图')
  })
}
