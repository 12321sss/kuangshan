package com.ganfeng.rs.boundary;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * AOI 边界（aoi_boundary 表）—— 客户提供的边界文件导入后的统一存放处
 *
 * 为什么单独一张表，而不是塞进 project.boundaryJson：
 * 1. 一个项目可能有多类边界（矿权范围 / 实际扰动边界 / 生态缓冲区），
 *    方案红线明确要求这三类**分开管理**，混在一个 JSON 里必然被误用；
 * 2. 越界开采检测只认 boundaryType=PERMIT 的记录，需要能按类型查；
 * 3. 一次导入常含多个要素（多个矿权区块），需要逐条记录、能单独启用/删除。
 *
 * 几何统一存 **WGS84 经纬度**的外环 + 内洞（JSON），
 * 与解译结果、Cesium 渲染、风险分析的坐标口径一致。
 */
@Entity
@Table(name = "aoi_boundary")
public class AoiBoundary {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long projectId;

    @Column(nullable = false, length = 128)
    private String name;

    /**
     * 边界类型：
     * PERMIT      矿权范围（登记数据，越界检测的唯一基准）
     * DISTURBANCE 实际扰动边界（影像解译得出，不能当矿权用）
     * ECO         生态分析缓冲区
     */
    @Column(nullable = false, length = 16)
    private String boundaryType;

    /** 外环 + 内洞，格式 {"outer":[[lng,lat],...],"holes":[[[...]],...]} */
    @Lob
    @Column(columnDefinition = "LONGTEXT")
    private String geometryJson;

    /** 面积（公顷），按中心纬度做等距近似计算 */
    private double areaHa;

    private int vertexCount;

    /** 来源文件格式：SHP / GeoJSON / KML */
    @Column(length = 16)
    private String sourceFormat;

    /** 原始坐标系（如 EPSG:32650），仅作追溯，数据本身已转 WGS84 */
    @Column(length = 64)
    private String sourceCrs;

    /** 原始文件名，便于追溯是哪份客户资料 */
    @Column(length = 256)
    private String sourceFile;

    /** 解析时产生的提示（缺 .prj、按 WGS84 假定等），要如实展示给用户 */
    @Lob
    @Column(columnDefinition = "TEXT")
    private String warnings;

    @Column(length = 64)
    private String createdBy;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    protected AoiBoundary() {}

    public AoiBoundary(Long projectId, String name, String boundaryType, String geometryJson,
                       double areaHa, int vertexCount, String sourceFormat, String sourceCrs,
                       String sourceFile, String warnings, String createdBy) {
        this.projectId = projectId;
        this.name = name;
        this.boundaryType = boundaryType;
        this.geometryJson = geometryJson;
        this.areaHa = areaHa;
        this.vertexCount = vertexCount;
        this.sourceFormat = sourceFormat;
        this.sourceCrs = sourceCrs;
        this.sourceFile = sourceFile;
        this.warnings = warnings;
        this.createdBy = createdBy;
    }

    public Long getId() { return id; }
    public Long getProjectId() { return projectId; }
    public String getName() { return name; }
    public void setName(String v) { this.name = v; }
    public String getBoundaryType() { return boundaryType; }
    public void setBoundaryType(String v) { this.boundaryType = v; }
    public String getGeometryJson() { return geometryJson; }
    public double getAreaHa() { return areaHa; }
    public int getVertexCount() { return vertexCount; }
    public String getSourceFormat() { return sourceFormat; }
    public String getSourceCrs() { return sourceCrs; }
    public String getSourceFile() { return sourceFile; }
    public String getWarnings() { return warnings; }
    public String getCreatedBy() { return createdBy; }
    public LocalDateTime getCreatedAt() { return createdAt; }
}
