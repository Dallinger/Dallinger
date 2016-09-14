%
% Extract a number from a string "str"
% where "pattern" is a substring of str 
% with a * where the number should be
%
%  str=image222_happiness
%  pattern = mage*_hap
%  
% will return num = 22

function num = extract_num_from_string(str,pattern)

    k_star = strfind(pattern,'*');
    
    pat_left = pattern(1:k_star-1);
    pat_right = pattern(k_star+1:end);
    
    
    kleft = strfind(str,pat_left);
    kleft = kleft + length(pat_left);
    assert(numel(kleft)==1);
    
    kright = strfind(str,pat_right);
    kright = kright-1;
    kright(kright < kleft) = [];
    kright = min(kright);
    
    str_num = str(kleft:kright);
    num = str2double(str_num);
    assert(~isnan(num));
end