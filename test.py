class Solution:
    def searchRange(self, nums: List[int], target: int) -> List[int]:
        #binary search
        #amount
        left = 0
        right = len(nums) - 1
        mid = right // 2

        start = -1
        end = -1

        #binary search for start
        while start == -1:
            if mid == 0 | (nums[mid] == target & nums[mid - 1] != target):
                start = mid
            elif nums[mid] < target: 
                left = mid
                mid = (mid + right) // 2
            else:
                right = mid
                mid = (mid + left) // 2

        #then, binary search for end, by using length of remaining array
        mid = (len(array) - start + 1) // 2
        while end == -1:
            if mid == len(nums) - 1 | nums[mid] == target & nums[mid + 1] != target:
                end = mid
            elif nums[mid] != target:
                mid = (mid + start) // 2
            else: 
                mid = (mid + len(array)) // 2

        return [start, end]


 
