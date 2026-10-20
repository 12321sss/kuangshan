package com.ganfeng.rs.task;

import jakarta.persistence.*;

import java.time.LocalDateTime;

/**
 * 解译任务（tasks 表）
 * algoType: SEGMENTATION 语义分割 / CHANGE_DETECTION 变化检测 / INDEX 指数计算
 * status: PENDING / RUNNING / SUCCESS / FAILED
 */
@Entity
@Table(name = "tasks")
public class InterpretTask {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, length = 128)
    private String name;

    @Column(nullable = false)
    private Long projectId;

    @Column(nullable = false, length = 32)
    private String algoType;

    @Column(nullable = false, length = 16)
    private String status = "PENDING";

    @Column(nullable = false)
    private Integer progress = 0;

    @Column(length = 128)
    private String imageName;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    protected InterpretTask() {}

    public InterpretTask(String name, Long projectId, String algoType, String status,
                         Integer progress, String imageName, LocalDateTime createdAt) {
        this.name = name;
        this.projectId = projectId;
        this.algoType = algoType;
        this.status = status;
        this.progress = progress;
        this.imageName = imageName;
        this.createdAt = createdAt;
    }

    public Long getId() { return id; }
    public String getName() { return name; }
    public Long getProjectId() { return projectId; }
    public String getAlgoType() { return algoType; }
    public String getStatus() { return status; }
    public Integer getProgress() { return progress; }
    public String getImageName() { return imageName; }
    public LocalDateTime getCreatedAt() { return createdAt; }

    public void setStatus(String status) { this.status = status; }
    public void setProgress(Integer progress) { this.progress = progress; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
}
