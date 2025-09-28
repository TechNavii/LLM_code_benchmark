#include "sparse_matrix.h"

#include <stdexcept>

struct SparseMatrix::Impl {};

SparseMatrix::SparseMatrix(std::size_t, std::size_t) : impl_(nullptr) {
  throw std::logic_error("not implemented");
}

std::size_t SparseMatrix::rows() const noexcept {
  return 0;
}

std::size_t SparseMatrix::cols() const noexcept {
  return 0;
}

std::size_t SparseMatrix::nnz() const noexcept {
  return 0;
}

double SparseMatrix::get(std::size_t, std::size_t) const {
  throw std::logic_error("not implemented");
}

void SparseMatrix::set(std::size_t, std::size_t, double) {
  throw std::logic_error("not implemented");
}

SparseMatrix SparseMatrix::transpose() const {
  throw std::logic_error("not implemented");
}

SparseMatrix SparseMatrix::multiply(const SparseMatrix&) const {
  throw std::logic_error("not implemented");
}
