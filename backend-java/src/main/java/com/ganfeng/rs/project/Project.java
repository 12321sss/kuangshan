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
    public String getBoundaryJson() { return boundaryJson; }

    public void setName(String name) { this.name = name; }
    public void setRegion(String region) { this.region = region; }
    public void setStatus(String status) { this.status = status; }
    public void setManager(String manager) { this.manager = manager; }
    public void setDescription(String description) { this.description = description; }
    public void setMembers(List<String> members) { this.members = members; }
    public void setBoundaryJson(String boundaryJson) { this.boundaryJson = boundaryJson; }
}
