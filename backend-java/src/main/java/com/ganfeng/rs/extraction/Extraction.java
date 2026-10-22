package com.ganfeng.rs.extraction;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * 在线提取记录（extractions 表，元数据与统计值）
 * AOI 与结果几何 demo 期以 GeoJSON 坐标 JSON 存本表；接入空间库后迁移到 rs_geo.extraction_*
 */
@Entity
@Table(name = "extractions")
public class Extraction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long projectId;

    /** inference 返回的任务号：回调落库时用于幂等去重 */
    @Column(length = 64)
    private String taskId;

    /** 解译所用影像（imagery 表） */
    private Long imageryId;

    /** 命中像元数（诊断用：像元数 x 像元面积 = 提取面积） */
    private Integer pixelCount;

    @Column(nullable = false, length = 64)
    private String name;

    /** 提取类型：VEGETATION 植被 / WATER 水体 / PIT 采坑 / DUMP 排土场 / BARE 裸地扰动 */
    @Column(nullable = false, length = 16)
    private String classType;

    /** 数据源卫星：SENTINEL2 / LANDSAT9 / GF2 */
    @Column(nullable = false, length = 16)
    private String satellite;

    @Column(nullable = false)
    private Integer year;

    /**
     * 影像拍摄日期（时序播放按此排序；来源于所选影像的 acquisition_date，
     * 不是提取时间）。为空时回退到 year 参与排序。
     */
    @Column
    private java.time.LocalDate acquisitionDate;

    /** AOI 多边形环：[[lng,lat],...] JSON（真实解译链路下由前端提交、回调时回写） */
    @Column(columnDefinition = "longtext")
    private String aoiJson;

    /**
     * AOI 指纹（aoi_json 归一化后的哈希）：用于识别「同一 AOI 的不同期提取结果」，
     * 是时序播放与变化分析的分组依据。归一化消除了顶点顺序/起点差异。
     */
    @Column(length = 64)
    private String aoiSignature;

    /** 结果要素多边形集合：[[[lng,lat],...],...] JSON */
    @Column(nullable = false, columnDefinition = "longtext")
    private String featuresJson;

    @Column(nullable = false)
    private Double aoiAreaHa;

    @Column(nullable = false)
    private Double extractAreaHa;

    @Column(nullable = false)
    private Double coveragePct;

    /**
     * 解译方法：INDEX 指数阈值法 / SUPERVISED 监督分类 / FUSION 融合结果
     *
     * 为什么必须记：叠加分析要按方法筛数据（分类结果 ↔ 指数结果），
     * 只靠名称里有没有"监督分类"来猜太脆弱。
     */
    @Column(length = 16)
    private String method = "INDEX";

    /** 精度或融合元信息（JSON）：监督分类存 OA/Kappa/混淆矩阵；融合存策略与参与记录 */
    @Lob
    @Column(columnDefinition = "TEXT")
    private String accuracyJson;

    @Column(length = 64)
    private String createdBy;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    /**
     * 软删除标记：删除进回收站而非物理删除，防止演示现场误删丢数据。
     * 所有业务查询（时序/分析/报告/分享）都必须过滤 deleted=false。
     */
    @Column(nullable = false)
    private Boolean deleted = false;

    @Column
    private LocalDateTime deletedAt;

    @Column(length = 64)
    private String deletedBy;

    protected Extraction() {}

    public Long getId() { return id; }
    public Long getProjectId() { return projectId; }
    public String getTaskId() { return taskId; }
    public Long getImageryId() { return imageryId; }
    public Integer getPixelCount() { return pixelCount; }
    public String getName() { return name; }
    public String getClassType() { return classType; }
    public String getSatellite() { return satellite; }
    public Integer getYear() { return year; }
    public java.time.LocalDate getAcquisitionDate() { return acquisitionDate; }
    public String getAoiJson() { return aoiJson; }
    public String getAoiSignature() { return aoiSignature; }
    public String getFeaturesJson() { return featuresJson; }
    public Double getAoiAreaHa() { return aoiAreaHa; }
    public Double getExtractAreaHa() { return extractAreaHa; }
    public Double getCoveragePct() { return coveragePct; }
    public String getMethod() { return method; }
    public void setMethod(String v) { this.method = (v == null || v.isBlank()) ? "INDEX" : v; }
    public String getAccuracyJson() { return accuracyJson; }
    public void setAccuracyJson(String v) { this.accuracyJson = v; }
    public String getCreatedBy() { return createdBy; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public Boolean getDeleted() { return deleted; }
    public LocalDateTime getDeletedAt() { return deletedAt; }
    public String getDeletedBy() { return deletedBy; }

    public void setProjectId(Long projectId) { this.projectId = projectId; }
    public void setTaskId(String v) { this.taskId = v; }
    public void setImageryId(Long v) { this.imageryId = v; }
    public void setPixelCount(Integer v) { this.pixelCount = v; }
    public void setName(String name) { this.name = name; }
    public void setClassType(String classType) { this.classType = classType; }
    public void setSatellite(String satellite) { this.satellite = satellite; }
    public void setYear(Integer year) { this.year = year; }
    public void setAcquisitionDate(java.time.LocalDate v) { this.acquisitionDate = v; }
    public void setAoiJson(String aoiJson) { this.aoiJson = aoiJson; }
    public void setAoiSignature(String v) { this.aoiSignature = v; }
    public void setFeaturesJson(String featuresJson) { this.featuresJson = featuresJson; }
    public void setAoiAreaHa(Double v) { this.aoiAreaHa = v; }
    public void setExtractAreaHa(Double v) { this.extractAreaHa = v; }
    public void setCoveragePct(Double v) { this.coveragePct = v; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
    public void setCreatedAt(java.time.LocalDateTime v) { this.createdAt = v; }
    public void setDeleted(Boolean v) { this.deleted = v; }
    public void setDeletedAt(LocalDateTime v) { this.deletedAt = v; }
    public void setDeletedBy(String v) { this.deletedBy = v; }
}
