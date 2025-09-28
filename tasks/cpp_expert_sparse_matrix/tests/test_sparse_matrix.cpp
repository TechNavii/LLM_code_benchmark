#include "sparse_matrix.h"

#include <cmath>
#include <iostream>
#include <stdexcept>

namespace {

void expect(bool condition, const char* message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

void expect_close(double a, double b, double eps = 1e-9) {
  if (std::fabs(a - b) > eps) {
    throw std::runtime_error("values not close enough");
  }
}

void test_basic_api() {
  SparseMatrix matrix(3, 4);
  expect(matrix.rows() == 3, "rows mismatch");
  expect(matrix.cols() == 4, "cols mismatch");
  expect(matrix.nnz() == 0, "expected empty matrix");

  expect_close(matrix.get(1, 2), 0.0);
  matrix.set(1, 2, 5.0);
  expect(matrix.nnz() == 1, "nnz should increase");
  expect_close(matrix.get(1, 2), 5.0);
  matrix.set(1, 2, 0.0);
  expect(matrix.nnz() == 0, "setting zero should remove entry");
}

void test_transpose() {
  SparseMatrix m(2, 3);
  m.set(0, 1, 2.5);
  m.set(1, 2, -1.0);
  auto t = m.transpose();
  expect(t.rows() == 3 && t.cols() == 2, "transpose dimensions");
  expect_close(t.get(1, 0), 2.5);
  expect_close(t.get(2, 1), -1.0);
}

void test_multiply() {
  SparseMatrix a(2, 3);
  a.set(0, 0, 1.0);
  a.set(0, 2, 2.0);
  a.set(1, 1, 3.0);

  SparseMatrix b(3, 2);
  b.set(0, 1, 4.0);
  b.set(2, 0, -1.0);
  b.set(1, 1, 2.0);

  auto prod = a.multiply(b);
  expect(prod.rows() == 2 && prod.cols() == 2, "product dimensions");
  expect_close(prod.get(0, 0), -2.0);
  expect_close(prod.get(0, 1), 4.0);
  expect_close(prod.get(1, 1), 6.0);
}

void test_invalid_access() {
  SparseMatrix m(1, 1);
  bool caught = false;
  try {
    m.get(5, 0);
  } catch (const std::out_of_range&) {
    caught = true;
  }
  expect(caught, "expected out_of_range on invalid get");

  caught = false;
  try {
    m.set(0, 2, 1.0);
  } catch (const std::out_of_range&) {
    caught = true;
  }
  expect(caught, "expected out_of_range on invalid set");

  SparseMatrix a(1, 2);
  SparseMatrix b(3, 1);
  caught = false;
  try {
    (void)a.multiply(b);
  } catch (const std::invalid_argument&) {
    caught = true;
  }
  expect(caught, "expected invalid_argument on shape mismatch");
}

}  // namespace

int main() {
  try {
    test_basic_api();
    test_transpose();
    test_multiply();
    test_invalid_access();
  } catch (const std::exception& e) {
    std::cerr << "Test failure: " << e.what() << '\n';
    return 1;
  }
  std::cout << "All tests passed.\n";
  return 0;
}
