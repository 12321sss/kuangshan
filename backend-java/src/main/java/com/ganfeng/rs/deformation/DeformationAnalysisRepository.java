package com.ganfeng.rs.deformation;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface DeformationAnalysisRepository extends JpaRepository<DeformationAnalysis, Long> {

    /** 项目内未删除的形变分析（按创建时间倒序） */
    List<DeformationAnalysis> findByProjectIdAndDeletedFalseOrderByCreatedAtDesc(Long projectId);

    /** 项目内全部（含软删除，供回收站） */
    List<DeformationAnalysis> findByProjectIdOrderByCreatedAtDesc(Long projectId);
}
