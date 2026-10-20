package com.ganfeng.rs.extraction;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ExtractionRepository extends JpaRepository<Extraction, Long> {

    List<Extraction> findByProjectIdOrderByCreatedAtDesc(Long projectId);

    /** 按 inference 任务号查重（回调幂等） */
    List<Extraction> findByTaskId(String taskId);
}
