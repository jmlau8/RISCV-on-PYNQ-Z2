#define ARRAY_LEN 8
#ifndef RAM_BASE
#define RAM_BASE 0
#endif
#define RESULT_BASE (RAM_BASE + 0x400)

static int arr[ARRAY_LEN] = {42, 17, 93, 8, 55, 3, 71, 29};

static void swap(int *a, int *b) {
    int t = *a;
    *a = *b;
    *b = t;
}

static int partition(int *a, int lo, int hi) {
    int pivot = a[hi];
    int i = lo - 1;
    for (int j = lo; j < hi; j++) {
        if (a[j] < pivot) {
            i++;
            swap(&a[i], &a[j]);
        }
    }
    swap(&a[i + 1], &a[hi]);
    return i + 1;
}

static void quicksort(int *a, int lo, int hi) {
    if (lo < hi) {
        int p = partition(a, lo, hi);
        quicksort(a, lo, p - 1);
        quicksort(a, p + 1, hi);
    }
}

static volatile unsigned int * const status = (unsigned int *)(RESULT_BASE - 4);
static volatile int * const result = (int *)RESULT_BASE;

int main(void) {
    *status = 0xBEEF0001;
    quicksort(arr, 0, ARRAY_LEN - 1);
    for (int i = 0; i < ARRAY_LEN; i++) {
        result[i] = arr[i];
    }
    *status = 0xBEEF0002;
    while (1) {}
    return 0;
}
