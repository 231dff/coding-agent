;; 函数定义
(function_definition
  name: (identifier) @definition.function
  (#set! kind "function"))

;; 类定义
(class_definition
  name: (identifier) @definition.class
  (#set! kind "class"))

;; 方法定义（类内部的函数）
(class_definition
  body: (block
    (function_definition
      name: (identifier) @definition.method)))

;; 函数调用
(call
  function: (identifier) @reference.call)

;; 属性调用 (obj.method())
(call
  function: (attribute
    attribute: (identifier) @reference.call))

;; 导入语句
(import_statement
  name: (dotted_name) @reference.import)

(import_from_statement
  module_name: (dotted_name) @reference.import)

;; 赋值（模块级常量）
(module
  (expression_statement
    (assignment
      left: (identifier) @definition.constant)))