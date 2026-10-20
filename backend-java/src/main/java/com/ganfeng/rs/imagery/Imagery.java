package com.ganfeng.rs.imagery;

import jakarta.persistence.*;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 影像库（imagery 表）—— 两条解译路线的统一入口
 *
 * 路线一「上传遥感图像解译」：source=UPLOAD，用户上传高分影像（GF-2 等商业数据）
 *   filePath 指向落盘文件；坐标系由上传时选择（原样记录，不强制转换）
 * 路线二「在线提取」：source=SENTINEL2/LANDSAT9，平台按 AOI 从 Copernicus 检索公开数据
 *   productId 为公开数据源产品 ID；上传的缩略图存 quicklookPath
 *
 * 坐标系（crs字段）：上传时由用户选择，支持 EPSG 整数或 WKT；
 *   必须**原样记录**，前端在 Cesium 上定位时据此判断是否需要转换。
 *   这是硬性要求：GF-2 常见为 UTM 投影或 CGCS2000，若一律当 EPSG:4326 处理，
 *   影像会定位到几内亚湾去。
 *
 * 覆盖范围（west/south/east/north）：**统一存 WGS84 经纬度**，
 *   非 4326 的影像在入库时已换算过，前端可直接用于 Cesium 矩形定位。
 */
@Entity
@Table(name = "imagery")
public class Imagery {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long projectId;

    @Column(nullable = false, length = 128)
    private String name;

    /** 来源：UPLOAD 上传的高分影像 / SENTINEL2 / LANDSAT9 */
    @Column(nullable = false, length = 24)
    private String source;

    /** 上传影像的磁盘路径（source=UPLOAD 时有值） */
    @Column(length = 512)
    private String filePath;

    /** Copernicus 产品 ID（公开数据源时有值） */
    @Column(length = 64)
    private String productId;

    /** 原始文件名（上传时保留，便于溯源） */
    @Column(length = 255)
    private String originalName;

    /**
     * 坐标系：EPSG 整数（如 4326）或完整 WKT。
     * 上传时由用户选择；Sentinel-2 等已知源固定 EPSG:4326。
     */
    @Column(length = 128)
    private String crs;

    @Column(nullable = false)
    private LocalDate acquisitionDate;

    /** 云量百分比（%）；上传影像为 null */
    @Column
    private Double cloudCover;

    /** 地面分辨率（米/像素）：GF2≈0.8，S2=10，Landsat9=30 */
    @Column
    private Double resolutionM;

    /** 覆盖范围（WGS84 经纬度）：west/south/east/north */
    @Column(nullable = false)
    private Double west;

    @Column(nullable = false)
    private Double south;

    @Column(nullable = false)
    private Double east;

    @Column(nullable = false)
    private Double north;

    /** 缩略图路径（QUICKLOOK 或上传时生成） */
    @Column(length = 512)
    private String quicklookPath;

    /** 状态：READY 可用 / PROCESSING 处理中 / FAILED 失败 */
    @Column(nullable = false, length = 16)
    private String status = "READY";

    /** 收藏标记：客户常用影像一键星标，便于下次快速定位复用 */
    @Column(nullable = false)
    private Boolean favorite = false;

    @Column(length = 512)
    private String note;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    protected Imagery() {}

    public Long getId() { return id; }
    public Long getProjectId() { return projectId; }
    public String getName() { return name; }
    public String getSource() { return source; }
    public String getFilePath() { return filePath; }
    public String getProductId() { return productId; }
    public String getOriginalName() { return originalName; }
    public String getCrs() { return crs; }
    public LocalDate getAcquisitionDate() { return acquisitionDate; }
    public Double getCloudCover() { return cloudCover; }
    public Double getResolutionM() { return resolutionM; }
    public Double getWest() { return west; }
    public Double getSouth() { return south; }
    public Double getEast() { return east; }
    public Double getNorth() { return north; }
    public String getQuicklookPath() { return quicklookPath; }
    public String getStatus() { return status; }
    public Boolean getFavorite() { return favorite; }
    public String getNote() { return note; }
    public LocalDateTime getCreatedAt() { return createdAt; }

    public void setProjectId(Long v) { this.projectId = v; }
    public void setName(String v) { this.name = v; }
    public void setSource(String v) { this.source = v; }
    public void setFilePath(String v) { this.filePath = v; }
    public void setProductId(String v) { this.productId = v; }
    public void setOriginalName(String v) { this.originalName = v; }
    public void setCrs(String v) { this.crs = v; }
    public void setAcquisitionDate(LocalDate v) { this.acquisitionDate = v; }
    public void setCloudCover(Double v) { this.cloudCover = v; }
    public void setResolutionM(Double v) { this.resolutionM = v; }
    public void setWest(Double v) { this.west = v; }
    public void setSouth(Double v) { this.south = v; }
    public void setEast(Double v) { this.east = v; }
    public void setNorth(Double v) { this.north = v; }
    public void setQuicklookPath(String v) { this.quicklookPath = v; }
    public void setStatus(String v) { this.status = v; }
    public void setFavorite(Boolean v) { this.favorite = v; }
    public void setNote(String v) { this.note = v; }
    public void setCreatedAt(LocalDateTime v) { this.createdAt = v; }
}