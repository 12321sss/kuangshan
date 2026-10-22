package com.ganfeng.rs.project;

import jakarta.persistence.*;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

/**
 * 矿区项目（projects 表）
 * members 落 project_members 关联表——项目授权是高频读写，关联表比 JSON 合适
 */
@Entity
@Table(name = "projects")
public class Project {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 128)
    private String name;

    @Column(length = 128)
    private String region;

    /** RUNNING 进行中 / PLANNING 规划中 / ARCHIVED 已归档 */
    @Column(nullable = false, length = 16)
    private String status = "PLANNING";

    @Column(length = 64)
    private String manager;

    @Column(length = 512)
    private String description;

    // ------------------------------------------------------------------
    // 矿山业务档案字段（2026-10-22 补）
    // 目的：项目是所有数据（影像/边界/解译/安全评估）的归属单元，
    // 光有名称和区域不足以支撑交付与报告，需要记录矿权、开采方式等业务属性。
    // JPA ddl-auto=update 会自动补列，已有数据保持 null 不受影响。
    // ------------------------------------------------------------------

    /** 矿种：锂矿 / 铁矿 / 石灰岩 等（本项目主打硬岩锂矿） */
    @Column(length = 64)
    private String mineralType;

    /** 采矿许可证号（报告与合规章节引用） */
    @Column(length = 128)
    private String licenseNo;

    /** 矿权面积（km²）：与遥感测得的扰动面积对比，是越界分析的基准 */
    @Column
    private Double licenseAreaKm2;

    /** 开采方式：露天 / 井下 / 联合 */
    @Column(length = 32)
    private String miningMethod;

    /** 矿区中心点经度：新建项目后地图直接定位到这里，省得手动飞 */
    @Column
    private Double centerLng;

    /** 矿区中心点纬度 */
    @Column
    private Double centerLat;

    /** 客户方对接人（与内部负责人 manager 区分） */
    @Column(length = 64)
    private String contactPerson;

    /** 客户方联系方式 */
    @Column(length = 64)
    private String contactPhone;

    /** 影像/成果采用的坐标系（如 EPSG:4326 / CGCS2000），报告里要写明 */
    @Column(length = 64)
    private String crs;

    @Column(nullable = false)
    private LocalDate createdAt = LocalDate.now();

    /**
     * 合规边界（GeoJSON 格式 JSON）：矿权红线、实际扰动边界、生态红线三个多边形环。
     * 口径红线：矿权边界 ≠ 实际扰动边界，必须分开管理、分开展示。
     * 格式：{"mining":[[lng,lat],...], "disturbance":[...], "ecological":[...]}
     * demo 期由 DataSeeder 播种样区边界；生产期从矿权审批文件导入。
     */
    @Column(columnDefinition = "text")
    private String boundaryJson;

    /** 项目成员（用户名清单）：成员才能看到本项目数据；管理员不受限 */
    @ElementCollection(fetch = FetchType.LAZY)
    @CollectionTable(name = "project_members", joinColumns = @JoinColumn(name = "project_id"))
    @Column(name = "username", length = 64)
    private List<String> members = new ArrayList<>();

    protected Project() {}

    public Project(String name, String region, String status, String manager, String description) {
        this.name = name;
        this.region = region;
        this.status = status;
        this.manager = manager;
        this.description = description;
    }

    public Long getId() { return id; }
    public String getName() { return name; }
    public String getRegion() { return region; }
    public String getStatus() { return status; }
    public String getManager() { return manager; }
    public String getDescription() { return description; }
    public LocalDate getCreatedAt() { return createdAt; }
    public List<String> getMembers() { return members; }

    // ---- 矿山业务档案字段 ----
    public String getMineralType() { return mineralType; }
    public String getLicenseNo() { return licenseNo; }
    public Double getLicenseAreaKm2() { return licenseAreaKm2; }
    public String getMiningMethod() { return miningMethod; }
    public Double getCenterLng() { return centerLng; }
    public Double getCenterLat() { return centerLat; }
    public String getContactPerson() { return contactPerson; }
    public String getContactPhone() { return contactPhone; }
    public String getCrs() { return crs; }
    public String getBoundaryJson() { return boundaryJson; }

    public void setName(String name) { this.name = name; }
    public void setRegion(String region) { this.region = region; }
    public void setStatus(String status) { this.status = status; }
    public void setManager(String manager) { this.manager = manager; }
    public void setDescription(String description) { this.description = description; }
    public void setMineralType(String v) { this.mineralType = v; }
    public void setLicenseNo(String v) { this.licenseNo = v; }
    public void setLicenseAreaKm2(Double v) { this.licenseAreaKm2 = v; }
    public void setMiningMethod(String v) { this.miningMethod = v; }
    public void setCenterLng(Double v) { this.centerLng = v; }
    public void setCenterLat(Double v) { this.centerLat = v; }
    public void setContactPerson(String v) { this.contactPerson = v; }
    public void setContactPhone(String v) { this.contactPhone = v; }
    public void setCrs(String v) { this.crs = v; }
    public void setMembers(List<String> members) { this.members = members; }
    public void setBoundaryJson(String boundaryJson) { this.boundaryJson = boundaryJson; }
}
