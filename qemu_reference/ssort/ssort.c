/* "Skew sort": heap sort using a skew heap (self-adjusting heap). Insert every key, then
   repeatedly remove the minimum. Fixed array, no library calls, RV32I only (no multiply). */
#define ARRAY_LEN 12
#ifndef RAM_BASE
#define RAM_BASE 0
#endif
#define RESULT_BASE (RAM_BASE + 0x2000)

struct node { int key; struct node *l, *r; };

static int arr[ARRAY_LEN] = {42, 17, 93, 8, 55, 3, 71, 29, 64, 11, 87, 26};
static struct node pool[ARRAY_LEN];

static struct node *merge(struct node *a, struct node *b) {
    if (!a) return b;
    if (!b) return a;
    if (b->key < a->key) { struct node *t = a; a = b; b = t; }
    struct node *t = a->l;
    a->l = merge(a->r, b);
    a->r = t;
    return a;
}

static volatile unsigned int * const status = (unsigned int *)(RESULT_BASE - 4);
static volatile int * const result = (int *)RESULT_BASE;

int main(void) {
    struct node *heap = 0;
    *status = 0xBEEF0001;
#ifdef REPS   /* optional: repeat the whole sort REPS times (speed experiments) */
    for (int rep = 0; rep < REPS; rep++) {
        heap = 0;
#endif
    for (int i = 0; i < ARRAY_LEN; i++) {
        pool[i].key = arr[i];
        pool[i].l = 0;
        pool[i].r = 0;
        heap = merge(heap, &pool[i]);
    }
    for (int i = 0; i < ARRAY_LEN; i++) {
        result[i] = heap->key;
        heap = merge(heap->l, heap->r);
    }
#ifdef REPS
    }
#endif
    *status = 0xBEEF0002;
    while (1) {}
    return 0;
}
