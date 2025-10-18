   if c.head == e {
       return
   }
   c.remove(e)
   c.addToFront(e)
   }
   return &Cache{
       capacity: capacity,
       items:    make(map[string]*entry, capacity),
   }
}
// Get fetches a value, marking the key as recently used.
func (c *Cache) Get(key string) (any, bool) {
   c.mu.Lock()
   defer c.mu.Unlock()
   e, ok := c.items[key]
   if !ok {
       return nil, false
   }
   c.moveToFront(e)
   return e.value, true
}
// Set inserts or updates a value, evicting the least recently used entry.
func (c *Cache) Set(key string, value any) {
   c.mu.Lock()
   defer c.mu.Unlock()
   if e, ok := c.items[key]; ok {
       e.value = value
       c.moveToFront(e)
       return
   }
   e := &entry{key: key, value: value}
   c.items[key] = e
   c.addToFront(e)
   c.size++
   if c.size > c.capacity {
       // evict tail
       old := c.tail
       c.remove(old)
       delete(c.items, old.key)
       c.size--
   }
}
// Len returns the current number of entries.
func (c *Cache) Len() int {
   c.mu.Lock()
   defer c.mu.Unlock()
   return c.size
}

// entry is a node in a doubly linked list for LRU.
type entry struct {
   key   string
   value any
   prev  *entry
   next  *entry
}

// addToFront adds e as most recently used.
func (c *Cache) addToFront(e *entry) {
   if c.head == nil {
       c.head, c.tail = e, e
       return
   }
   e.next = c.head
   c.head.prev = e
   c.head = e
}

// remove unlinks e from the list.
func (c *Cache) remove(e *entry) {
   if e.prev != nil {
       e.prev.next = e.next
   } else {
       c.head = e.next
   }
   if e.next != nil {
       e.next.prev = e.prev
   } else {
       c.tail = e.prev
   }
   e.prev, e.next = nil, nil
}

// moveToFront moves e to the head.
func (c *Cache) moveToFront(e *entry) {
   if c.head == e {
       return
   }
   c.remove(e)
   c.addToFront(e)
}
    panic("not implemented")
}

// Len returns the current number of entries.
func (c *Cache) Len() int {
    // TODO: implement
    panic("not implemented")
}
