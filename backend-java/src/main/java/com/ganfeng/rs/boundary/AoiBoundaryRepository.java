package com.ganfeng.rs.boundary;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface AoiBoundaryRepository extends JpaRepository<AoiBoundary, Long> {

    List<AoiBoundary> findByProjectIdOrderByCreatedAtDesc(Long projectId);

    List<AoiBoundary> findByProjectIdAndBoundaryTypeOrderByCreatedAtDesc(Long projectId, String boundaryType);

    List<AoiBoundary> findByProjectIdOrderByIdAsc(Long projectId);
}
