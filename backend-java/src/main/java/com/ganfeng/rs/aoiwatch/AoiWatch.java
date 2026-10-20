package com.ganfeng.rs.aoiwatch;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * AOI 监测订阅（aoi_watch 表）
 *
 * 客户在地图上圈一块关注区域，保存为「关注区」后系统可持续跟踪该区域的地物变化，
 * 而不是每次重新圈选。变化检测复用 extractions 表的 aoiSignature 分组结果：
 * 同一 AOI 的历次解译通过指纹关联，检查时比较最近两期面积差。
 *
 * 设计要点：
 * - aoiSignature 与 ExtractionService.aoiSignature 算法一致，才能匹配上历史解译
 * - 存 classType 是因为同一块地的不同地物类型要分开跟踪
 * - lastCheckAreaHa / lastCheckDate 记录上次检查时的快照，便于算增量
 */
@Entity
@Table(name = "aoi_watch", indexes = {
        @Index(name = "idx_aoi_watch_project", columnList = "projectId"),
        @Index(name = "idx_aoi_watch_sig", columnList = "signature")
})
public class AoiWatch {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false)
    private Long projectId;

    /** 创建人账号：只让自己看到自己的关注区（管理员可见全部） */
    @Column(nullable = false, length = 64)
    private String username;

    /** 关注区名称（默认按地物类型 + 日期生成，客户可改） */
    @Column(nullable = false, length = 128)
    private String name;

    /** AOI 环坐标 JSON：[[lng,lat],...] */
    @Column(nullable = false, columnDefinition = "longtext")
    private String aoiJson;

    /** AOI 指纹：与 extraction 表同算法，用于匹配历史解译记录 */
    @Column(length = 64)
    private String signature;

    /** 跟踪的地物类型：VEGETATION / PIT / BARE 等 */
    @Column(nullable = false, length = 32)
    private String classType;

    /** 上次检查时的面积（公顷），用于算变化量 */
    @Column
    private Double lastCheckAreaHa;

    /** 上次检查时的影像日期 */
    @Column(length = 32)
    private String lastCheckDate;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    @Column
    private LocalDateTime lastCheckAt;

    protected AoiWatch() {}

    public AoiWatch(Long projectId, String username, String name, String aoiJson,
                    String signature, String classType) {
        this.projectId = projectId;
        this.username = username;
        this.name = name;
        this.aoiJson = aoiJson;
        this.signature = signature;
        this.classType = classType;
    }

    public Long getId() { return id; }
    public Long getProjectId() { return projectId; }
    public String getUsername() { return username; }
    public String getName() { return name; }
    public String getAoiJson() { return aoiJson; }
    public String getSignature() { return signature; }
    public String getClassType() { return classType; }
    public Double getLastCheckAreaHa() { return lastCheckAreaHa; }
    public String getLastCheckDate() { return lastCheckDate; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public LocalDateTime getLastCheckAt() { return lastCheckAt; }

    public void setName(String name) { this.name = name; }
    public void setClassType(String classType) { this.classType = classType; }
    public void setLastCheckAreaHa(Double v) { this.lastCheckAreaHa = v; }
    public void setLastCheckDate(String v) { this.lastCheckDate = v; }
    public void setLastCheckAt(LocalDateTime v) { this.lastCheckAt = v; }
}
