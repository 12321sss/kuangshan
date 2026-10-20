package com.ganfeng.rs.dict;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface DictItemRepository extends JpaRepository<DictItem, Long> {

    List<DictItem> findByCategoryOrderBySortOrderAsc(String category);

    List<DictItem> findAllByOrderByCategoryAscSortOrderAsc();

    Optional<DictItem> findByCategoryAndCode(String category, String code);

    long countByCategory(String category);
}
