package com.ganfeng.rs.extraction;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ExtractionRepository extends JpaRepository<Extraction, Long> {

    List<Extraction> findByProjectIdOrderByCreatedAtDesc(Long projectId);

    /** 按 inference 任务号查重（回调幂等） */
    List<Extraction> findByTaskId(String taskId);

    /**
     * 按 AOI 指纹查该区域的全部解译记录（按影像日期升序），
     * 供「AOI 监测订阅」检查同一关注区的历史变化。
     */
    List<Extraction> findByAoiSignatureOrderByAcquisitionDateAsc(String aoiSignature);
}
