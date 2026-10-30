package com.ganfeng.rs.deformation;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/**
 * 形变分析结果。
 *
 * 存「形变速率场 + 时序」的分析结果元数据：速度/加速度/信噪比等判定指标。
 * 速率场栅格（GeoTIFF）存本地磁盘，这里只存路径与统计摘要，避免数据库塞大栅格。
 *
 * 数据来源（source）：
 *   NISAR      NISAR L 波段 GUNW SBAS
 *   SENTINEL1  Sentinel-1 C 波段 SBAS
 *   FUSION     多源融合
 *   GNSS       地面 GNSS/边坡雷达实测
 */
@Entity
@Table(name = "deformation_analyses")
public class DeformationAnalysis {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 所属项目（跨项目隔离依据） */
    @Column(nullable = false)
    private Long projectId;

    @Column(nullable = false, length = 64)
    private String name;

    /** 数据来源：NISAR / SENTINEL1 / FUSION / GNSS */
    @Column(nullable = false, length = 16)
    private String source;

    /** 轨道号（SAR 数据有，GNSS 为 null） */
    private Integer track;

    /** 分析区环 WGS84（JSON，[[lng,lat],...]） */
    @Column(columnDefinition = "longtext")
    private String aoiJson;

    /** 分析区范围（JSON：west/south/east/north） */
    @Column(length = 256)
    private String bboxJson;

    /** 时序时间轴（JSON，小数年数组） */
    @Column(columnDefinition = "TEXT")
    private String timesJson;

    /** 速率场统计（JSON：median/p5/p95/min/max） */
    @Column(columnDefinition = "TEXT")
    private String velocityJson;

    /** 判定指标（JSON：速度/加速度/信噪比/失稳外推） */
    @Column(columnDefinition = "TEXT")
    private String statsJson;

    /** 速率场 GeoTIFF 的本地路径（空表示未落栅格） */
    @Column(length = 512)
    private String velocityTifPath;

    /** 数据是否可靠（信噪比达标）；false 时前端须标注"仅供参考" */
    @Column(nullable = false)
    private Boolean reliable = false;

    @Column(length = 64)
    private String createdBy;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    /** 软删除标记：与 extractions 表一致，进回收站而非物理删除 */
    @Column(nullable = false)
    private Boolean deleted = false;

    @Column
    private LocalDateTime deletedAt;

    @Column(length = 64)
    private String deletedBy;

    // ---- getters / setters ----

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getProjectId() { return projectId; }
    public void setProjectId(Long projectId) { this.projectId = projectId; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }
    public Integer getTrack() { return track; }
    public void setTrack(Integer track) { this.track = track; }
    public String getAoiJson() { return aoiJson; }
    public void setAoiJson(String aoiJson) { this.aoiJson = aoiJson; }
    public String getBboxJson() { return bboxJson; }
    public void setBboxJson(String bboxJson) { this.bboxJson = bboxJson; }
    public String getTimesJson() { return timesJson; }
    public void setTimesJson(String timesJson) { this.timesJson = timesJson; }
    public String getVelocityJson() { return velocityJson; }
    public void setVelocityJson(String velocityJson) { this.velocityJson = velocityJson; }
    public String getStatsJson() { return statsJson; }
    public void setStatsJson(String statsJson) { this.statsJson = statsJson; }
    public String getVelocityTifPath() { return velocityTifPath; }
    public void setVelocityTifPath(String velocityTifPath) { this.velocityTifPath = velocityTifPath; }
    public Boolean getReliable() { return reliable; }
    public void setReliable(Boolean reliable) { this.reliable = reliable; }
    public String getCreatedBy() { return createdBy; }
    public void setCreatedBy(String createdBy) { this.createdBy = createdBy; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public Boolean getDeleted() { return deleted; }
    public void setDeleted(Boolean deleted) { this.deleted = deleted; }
    public LocalDateTime getDeletedAt() { return deletedAt; }
    public void setDeletedAt(LocalDateTime deletedAt) { this.deletedAt = deletedAt; }
    public String getDeletedBy() { return deletedBy; }
    public void setDeletedBy(String deletedBy) { this.deletedBy = deletedBy; }
}
