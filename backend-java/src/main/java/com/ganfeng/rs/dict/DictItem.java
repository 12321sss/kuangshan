package com.ganfeng.rs.dict;

import jakarta.persistence.*;

/**
 * 数据字典项（dict_items 表）：集中管理地物类型、告警级别、单位等枚举的
 * 中文名与颜色，避免同一套编码在前后端多处硬编码。
 */
@Entity
@Table(name = "dict_items", uniqueConstraints =
        @UniqueConstraint(name = "uk_dict_cat_code", columnNames = {"category", "code"}))
public class DictItem {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    /** 分类：CLASS_TYPE 地物类型 / ALARM_LEVEL 告警级别 / UNIT 单位 */
    @Column(nullable = false, length = 32)
    private String category;

    @Column(nullable = false, length = 64)
    private String code;

    @Column(nullable = false, length = 64)
    private String label;

    /** 展示颜色（十六进制），前端图层渲染直接取用 */
    @Column(length = 16)
    private String color;

    @Column(nullable = false)
    private Integer sortOrder = 0;

    protected DictItem() {}

    public DictItem(String category, String code, String label, String color, int sortOrder) {
        this.category = category;
        this.code = code;
        this.label = label;
        this.color = color;
        this.sortOrder = sortOrder;
    }

    public Long getId() { return id; }
    public String getCategory() { return category; }
    public String getCode() { return code; }
    public String getLabel() { return label; }
    public String getColor() { return color; }
    public Integer getSortOrder() { return sortOrder; }

    public void setLabel(String label) { this.label = label; }
    public void setColor(String color) { this.color = color; }
    public void setSortOrder(Integer sortOrder) { this.sortOrder = sortOrder; }
}
