# C++ Expert Task: Sparse Matrix Algebra

Implement a cache-friendly sparse matrix in `workspace/sparse_matrix.{h,cpp}` supporting:

```cpp
class SparseMatrix {
 public:
  SparseMatrix(std::size_t rows, std::size_t cols);

  std::size_t rows() const noexcept;
  std::size_t cols() const noexcept;
  std::size_t nnz() const noexcept;  // number of stored entries

  double get(std::size_t row, std::size_t col) const;
  void set(std::size_t row, std::size_t col, double value);

  SparseMatrix transpose() const;
  SparseMatrix multiply(const SparseMatrix& rhs) const;
};
```

Requirements:

- Use a compressed sparse row (CSR) representation. Operations must be `O(nnz)` for iteration.
- `set` should insert or update values; writing zero removes the entry.
- Guard against out-of-range indices by throwing `std::out_of_range`.
- `multiply` performs matrix multiplication; reject shape mismatches with `std::invalid_argument`.
- `transpose` returns a new matrix without mutating the original.
- Keep the data structure exception safe and avoid duplicate entries or denormalised zero values.

Tests validate CSR integrity, multiplication correctness, removal of zero entries, and behaviour on degenerate matrices.
