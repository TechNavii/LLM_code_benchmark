#ifndef SPARSE_MATRIX_H
#define SPARSE_MATRIX_H

#include <cstddef>

class SparseMatrix {
 public:
  SparseMatrix(std::size_t rows, std::size_t cols);

  std::size_t rows() const noexcept;
  std::size_t cols() const noexcept;
  std::size_t nnz() const noexcept;

  double get(std::size_t row, std::size_t col) const;
  void set(std::size_t row, std::size_t col, double value);

  SparseMatrix transpose() const;
  SparseMatrix multiply(const SparseMatrix& rhs) const;

 private:
  struct Impl;
  Impl* impl_;
};

#endif
