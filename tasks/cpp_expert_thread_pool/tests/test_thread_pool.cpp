#include "../workspace/thread_pool.h"

#include <atomic>
#include <chrono>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>

namespace {

void assert_true(bool condition, const char* message) {
    if (!condition) {
        std::cerr << "Assertion failed: " << message << std::endl;
        std::exit(1);
    }
}

void test_completes_all_tasks() {
    ThreadPool pool(4);
    std::atomic<int> counter{0};
    std::vector<std::future<void>> futures;
    for (int i = 0; i < 100; ++i) {
        futures.push_back(pool.enqueue([&counter]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            counter.fetch_add(1, std::memory_order_relaxed);
        }));
    }
    for (auto& fut : futures) {
        fut.get();
    }
    assert_true(counter.load() == 100, "All tasks should complete");
    assert_true(pool.size() == 4, "ThreadPool size must remain stable");
}

void test_destructor_waits_for_tasks() {
    std::atomic<bool> started{false};
    std::atomic<bool> finished{false};
    {
        ThreadPool pool(2);
        pool.enqueue([&]() {
            started.store(true, std::memory_order_release);
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            finished.store(true, std::memory_order_release);
        });
        // Allow worker to start
        while (!started.load(std::memory_order_acquire)) {
        }
    }
    assert_true(finished.load(std::memory_order_acquire),
                "Destructor must wait for running tasks to finish");
}

void test_waits_with_predicate() {
    ThreadPool pool(1);
    std::atomic<int> result{0};
    for (int i = 0; i < 10; ++i) {
        pool.enqueue([&result]() { result.fetch_add(1, std::memory_order_relaxed); });
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    pool.enqueue([&result]() { result.fetch_add(1, std::memory_order_relaxed); });
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    assert_true(result.load() >= 11, "Condition variable must handle repeated notifications");
}

void test_stop_after_drain() {
    ThreadPool pool(2);
    std::atomic<int> counter{0};
    for (int i = 0; i < 20; ++i) {
        pool.enqueue([&counter]() {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            counter.fetch_add(1, std::memory_order_relaxed);
        });
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    assert_true(counter.load() > 0, "Tasks should begin executing");
}

}

int main() {
    test_completes_all_tasks();
    test_destructor_waits_for_tasks();
    test_waits_with_predicate();
    test_stop_after_drain();
    std::cout << "All tests passed." << std::endl;
    return 0;
}
