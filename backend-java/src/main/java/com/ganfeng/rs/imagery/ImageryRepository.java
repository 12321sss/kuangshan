package com.ganfeng.rs.imagery;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ImageryRepository extends JpaRepository<Imagery, Long> {

    List<Imagery> findByProjectIdOrderByAcquisitionDateDesc(Long projectId);

    List<Imagery> findByProjectIdAndSourceOrderByAcquisitionDateDesc(Long projectId, String source);
}