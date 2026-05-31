#pragma once

#include <atomic>
#include <memory>
#include <optional>

/**
 * @brief Simple Single-Producer Single-Consumer (SPSC) Lock-Free Queue
 * 
 * Specifically designed for pushing LED effects from the Audio Thread (Producer)
 * to the Hardware Background Thread (Consumer).
 */
template<typename T, size_t Size = 256>
class LockFreeQueue {
public:
    static_assert((Size & (Size - 1)) == 0, "Size must be a power of 2");

    LockFreeQueue() : head(0), tail(0) {}

    /**
     * @brief Push an item into the queue.
     * @return true if successful, false if the queue is full.
     */
    bool push(const T& item) {
        size_t current_tail = tail.load(std::memory_order_relaxed);
        size_t next_tail = (current_tail + 1) & (Size - 1);

        if (next_tail == head.load(std::memory_order_acquire)) {
            return false; // Queue full
        }

        buffer[current_tail] = item;
        tail.store(next_tail, std::memory_order_release);
        return true;
    }

    /**
     * @brief Pop an item from the queue.
     * @return std::optional containing the item, or nullopt if empty.
     */
    std::optional<T> pop() {
        size_t current_head = head.load(std::memory_order_relaxed);

        if (current_head == tail.load(std::memory_order_acquire)) {
            return std::nullopt; // Queue empty
        }

        T item = buffer[current_head];
        head.store((current_head + 1) & (Size - 1), std::memory_order_release);
        return item;
    }

private:
    T buffer[Size];
    std::atomic<size_t> head;
    std::atomic<size_t> tail;
};
